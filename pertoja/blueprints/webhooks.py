"""Blueprint de recebimento e validação fail-closed de webhooks de pagamento."""

import hashlib

from flask import Blueprint, jsonify, request

from pertoja._compat import resolve_compat
from pertoja.db.connection import DBIntegrityError
from pertoja.extensions import compat_get_db_connection, rate_limit, row_get
from pertoja.payments import (
    GatewayNotConfiguredError,
    PaymentGatewayError,
    WebhookSignatureError,
    get_payment_adapter,
)
from pertoja.services.payments_logic import (
    VALID_PAYMENT_GATEWAYS,
    settle_payment_and_sync_escrow,
)

webhooks_bp = Blueprint("webhooks", __name__)


@webhooks_bp.route("/api/webhooks/payments", methods=["POST"])
@webhooks_bp.route("/api/webhooks/payments/<gateway>", methods=["POST"])
@rate_limit(120, 60)
def payment_gateway_webhook(gateway=None):
    """Recebe eventos webhook verificando assinatura HMAC/timestamp antes de gravar no banco."""
    gw = (gateway or request.args.get("gateway") or request.headers.get("X-Payment-Gateway") or "").strip().lower()
    if gw not in VALID_PAYMENT_GATEWAYS:
        return jsonify({"error": "Gateway de webhook inválido."}), 400

    raw_body = request.get_data(cache=False) or b""
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    adapter_factory = resolve_compat("app", "get_payment_adapter", get_payment_adapter)
    try:
        adapter = adapter_factory(gw)
        event = adapter.verify_webhook(raw_body=raw_body, headers=request.headers, query_params=request.args)
    except WebhookSignatureError as exc:
        return jsonify({"error": str(exc), "code": exc.code}), 401
    except GatewayNotConfiguredError as exc:
        return jsonify({"error": str(exc), "code": exc.code}), exc.http_status
    except PaymentGatewayError as exc:
        return jsonify({"error": str(exc), "code": exc.code}), exc.http_status

    event_id = str(event.get("event_id") or "").strip() or payload_hash
    event_type = str(event.get("event_type") or "unknown").strip()
    gateway_payment_id = event.get("gateway_payment_id")
    gateway_reference = event.get("gateway_reference")
    event_public_id = event.get("public_id")
    mapped_status = event.get("mapped_status")
    payload_json = raw_body.decode("utf-8", errors="replace")

    conn = compat_get_db_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO payment_webhooks (
                    gateway, event_id, event_type, gateway_payment_id,
                    signature_valid, processing_status, payload_hash, payload_json
                )
                VALUES (?, ?, ?, ?, 1, 'received', ?, ?)
            """,
                (gw, event_id, event_type, gateway_payment_id, payload_hash, payload_json),
            )
            webhook_id = cursor.lastrowid
        except DBIntegrityError:
            conn.rollback()
            return jsonify({"status": "duplicate_ignored", "event_id": event_id}), 200

        tx = None
        if gateway_payment_id:
            tx = conn.execute(
                "SELECT * FROM payment_transactions WHERE gateway = ? AND gateway_payment_id = ?",
                (gw, str(gateway_payment_id)),
            ).fetchone()
        if not tx and gateway_reference:
            tx = conn.execute(
                "SELECT * FROM payment_transactions WHERE gateway = ? AND (gateway_reference = ? OR gateway_payment_id = ?)",
                (gw, str(gateway_reference), str(gateway_reference)),
            ).fetchone()
        if not tx and gateway_payment_id:
            tx = conn.execute(
                "SELECT * FROM payment_transactions WHERE gateway = ? AND gateway_reference = ?",
                (gw, str(gateway_payment_id)),
            ).fetchone()
        if not tx and event_public_id:
            tx = conn.execute(
                "SELECT * FROM payment_transactions WHERE gateway = ? AND public_id = ?",
                (gw, str(event_public_id)),
            ).fetchone()
        if not tx and gateway_payment_id:
            tx = conn.execute(
                "SELECT * FROM payment_transactions WHERE gateway = ? AND public_id = ?",
                (gw, str(gateway_payment_id)),
            ).fetchone()

        if not tx or mapped_status == "ignored":
            conn.execute(
                """
                UPDATE payment_webhooks
                SET processing_status = 'ignored', processed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (webhook_id,),
            )
            conn.commit()
            return jsonify({"status": "ignored", "event_id": event_id}), 200

        order = conn.execute("SELECT * FROM orders WHERE id = ?", (tx["order_id"],)).fetchone()
        if mapped_status == "paid" and order:
            event_amount_cents = event.get("amount_cents")
            if event_amount_cents is not None and int(event_amount_cents) < int(tx["amount_cents"]):
                conn.execute(
                    """
                    UPDATE payment_webhooks
                    SET processing_status = 'ignored', error_message = 'Underpayment mismatch', processed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (webhook_id,),
                )
                conn.commit()
                return jsonify({"status": "amount_mismatch_ignored", "event_id": event_id}), 200
            if gateway_payment_id and str(gateway_payment_id) != str(row_get(tx, "gateway_payment_id") or ""):
                fallback_ref = (
                    row_get(tx, "gateway_reference") or gateway_reference or row_get(tx, "gateway_payment_id")
                )
                conn.execute(
                    """
                    UPDATE payment_transactions
                    SET gateway_payment_id = ?, gateway_reference = COALESCE(gateway_reference, ?),
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (str(gateway_payment_id), fallback_ref, tx["id"]),
                )
            ok, _ = settle_payment_and_sync_escrow(conn, tx, order)
            if not ok:
                conn.rollback()
                try:
                    conn.execute(
                        """
                        INSERT INTO payment_webhooks (
                            gateway, event_id, event_type, gateway_payment_id,
                            signature_valid, processing_status, payload_hash, payload_json, processed_at
                        )
                        VALUES (?, ?, ?, ?, 1, 'ignored', ?, ?, CURRENT_TIMESTAMP)
                    """,
                        (gw, event_id, event_type, gateway_payment_id, payload_hash, payload_json),
                    )
                    conn.commit()
                except DBIntegrityError:
                    conn.rollback()
                return jsonify({"status": "ignored", "event_id": event_id}), 200
        elif mapped_status in ("failed", "expired", "cancelled"):
            conn.execute(
                """
                UPDATE payment_transactions
                SET status = ?, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND escrow_synced = 0 AND status IN ('pending', 'requires_action', 'authorized')
            """,
                (mapped_status, tx["id"]),
            )

        conn.execute(
            """
            UPDATE payment_webhooks
            SET processing_status = 'processed', processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """,
            (webhook_id,),
        )
        conn.commit()
        return jsonify({"status": "processed", "event_id": event_id}), 200
    finally:
        conn.close()
