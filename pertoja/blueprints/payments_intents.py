"""Rotas de criação, confirmação e estorno de intenções de pagamento em payments_bp."""

import os
import secrets

from flask import jsonify, request

from pertoja._compat import resolve_compat
from pertoja.db.connection import DBIntegrityError
from pertoja.extensions import (
    compat_get_db_connection,
    get_current_user,
    rate_limit,
    require_active_account,
    row_get,
)
from pertoja.payments import (
    GatewayNotConfiguredError,
    PaymentGatewayError,
    get_payment_adapter,
    is_sandbox_enabled,
)
from pertoja.services.payments_logic import (
    VALID_PAYMENT_GATEWAYS,
    VALID_PAYMENT_METHODS,
    check_idempotency,
    compute_request_hash,
    contains_forbidden_card_fields,
    extract_idempotency_key,
    lookup_payment_tx,
    save_idempotency,
    settle_payment_and_sync_escrow,
)


def register_payment_intent_routes(payments_bp) -> None:
    """Anexa rotas de intents, confirmação e estorno no payments_bp."""

    @payments_bp.route("/api/payments/intents", methods=["POST"])
    @rate_limit(20, 60)
    def create_payment_intent():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória.", "code": "UNAUTHORIZED"}), 401
        if user["tipo"] != "cliente":
            return jsonify({"error": "Apenas clientes podem iniciar pagamentos.", "code": "FORBIDDEN"}), 403
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        if contains_forbidden_card_fields(data):
            return jsonify(
                {"error": "Dados brutos de cartão (PAN/CVV) não são permitidos.", "code": "PCI_VIOLATION"}
            ), 400

        try:
            order_id = int(data.get("order_id"))
        except (ValueError, TypeError):
            return jsonify({"error": "order_id inválido."}), 400

        gateway = str(data.get("gateway") or ("sandbox" if is_sandbox_enabled() else "mercadopago")).strip().lower()
        if gateway not in VALID_PAYMENT_GATEWAYS:
            return jsonify({"error": "Gateway de pagamento inválido."}), 400
        if gateway == "sandbox" and not is_sandbox_enabled():
            return jsonify({"error": "Gateway sandbox desabilitado em produção.", "code": "SANDBOX_DISABLED"}), 403

        method = str(data.get("method") or data.get("metodo_pagamento") or "pix").strip().lower()
        if method not in VALID_PAYMENT_METHODS:
            return jsonify({"error": "Método de pagamento inválido."}), 400

        payment_method_id = data.get("payment_method_id")
        if payment_method_id is not None:
            try:
                payment_method_id = int(payment_method_id)
            except (ValueError, TypeError):
                return jsonify({"error": "payment_method_id inválido."}), 400

        idempotency_key = extract_idempotency_key(data)

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404
            if order["cliente_id"] != user["id"]:
                return jsonify({"error": "Sem permissão para pagar pedido de outro cliente."}), 403
            if order["status"] in ("cancelado", "em_disputa"):
                return jsonify({"error": f"Não é possível pagar pedido com status '{order['status']}'."}), 400

            escrow_atual = row_get(order, "escrow_status", "pendente")
            if int(row_get(order, "pago", 0) or 0) == 1 or escrow_atual in (
                "retido",
                "aguardando_liberacao",
                "liberado",
            ):
                return jsonify({"error": "Pedido já pago ou em escrow."}), 409

            amount_cents = int(round(float(row_get(order, "preco_total", 0.0) or 0.0) * 100))
            if amount_cents <= 0:
                return jsonify({"error": "Valor do pedido inválido."}), 400

            if data.get("amount_cents") is not None:
                try:
                    client_cents = int(data.get("amount_cents"))
                except (ValueError, TypeError):
                    return jsonify({"error": "amount_cents inválido."}), 400
                if client_cents != amount_cents:
                    return jsonify({"error": "Valor divergente do valor oficial do pedido."}), 400

            if data.get("amount") is not None:
                try:
                    client_amount_cents = int(round(float(data.get("amount")) * 100))
                except (ValueError, TypeError):
                    return jsonify({"error": "amount inválido."}), 400
                if client_amount_cents != amount_cents:
                    return jsonify({"error": "Valor divergente do valor oficial do pedido."}), 400

            payment_method_token = None
            if payment_method_id is not None:
                pm_row = conn.execute(
                    "SELECT * FROM payment_methods WHERE id = ? AND user_id = ? AND active = 1",
                    (payment_method_id, user["id"]),
                ).fetchone()
                if not pm_row or pm_row["gateway"] != gateway:
                    return jsonify({"error": "Método de pagamento salvo não encontrado para este gateway."}), 404
                payment_method_token = pm_row["gateway_token"]

            req_hash = compute_request_hash(
                {
                    "order_id": order_id,
                    "gateway": gateway,
                    "method": method,
                    "amount_cents": amount_cents,
                    "payment_method_id": payment_method_id,
                }
            )
            idem_state, idem_payload = check_idempotency(conn, user["id"], "create_intent", idempotency_key, req_hash)
            if idem_state == "conflict":
                return jsonify(
                    {
                        "error": "Chave de idempotência reutilizada com parâmetros diferentes.",
                        "code": "IDEMPOTENCY_CONFLICT",
                    }
                ), 409
            if idem_state == "replay":
                status_code, body = idem_payload
                return jsonify(body), status_code

            service_row = conn.execute(
                "SELECT titulo, descricao, categoria FROM services WHERE id = ?", (row_get(order, "servico_id"),)
            ).fetchone()
            item_title = row_get(service_row, "titulo", "") or f"Pedido PertoJá #{order_id}"
            item_description = (
                row_get(service_row, "descricao", "") or f"Serviço contratado via PertoJá (Pedido #{order_id})"
            )

            public_id = f"pay_{secrets.token_hex(12)}"
            raw_return = str(data.get("return_url") or "").strip()
            if not raw_return or raw_return.startswith("/"):
                rel_path = raw_return if raw_return.startswith("/") else f"/pedido.html?order_id={order_id}"
                base_url = os.environ.get("PAYMENT_RETURN_BASE_URL", "").strip().rstrip("/")
                if not base_url:
                    req_root = (request.url_root or "").strip().rstrip("/")
                    if req_root.startswith("https://") and "localhost" not in req_root and "127.0.0.1" not in req_root:
                        base_url = req_root
                return_url = f"{base_url}{rel_path}" if base_url else rel_path
            else:
                return_url = raw_return

            payer_email = str(row_get(user, "email", "") or "").strip() or "pagamentos@pertoja.com.br"
            payer = {
                "id": user["id"],
                "email": payer_email,
                "name": row_get(user, "nome", ""),
                "cpf": str(data.get("cpf") or row_get(user, "cpf", "") or ""),
                "telefone": row_get(user, "telefone", ""),
                "cep": row_get(user, "cep", "") or row_get(order, "cep_cliente", ""),
                "endereco": row_get(user, "endereco", "") or row_get(order, "endereco_cliente", ""),
                "numero": row_get(user, "numero", "") or row_get(order, "numero_cliente", ""),
                "bairro": row_get(user, "bairro", "") or row_get(order, "bairro_cliente", ""),
                "cidade": row_get(user, "cidade", "") or row_get(order, "cidade_cliente", ""),
                "estado": row_get(user, "estado", "") or row_get(order, "estado_cliente", ""),
            }

            adapter_factory = resolve_compat("app", "get_payment_adapter", get_payment_adapter)
            try:
                adapter = adapter_factory(gateway)
                intent_res = adapter.create_intent(
                    public_id=public_id,
                    order_id=order_id,
                    amount_cents=amount_cents,
                    currency="BRL",
                    method=method,
                    description=f"Pedido PertoJá #{order_id}",
                    payer=payer,
                    return_url=return_url,
                    payment_method_token=payment_method_token,
                    metadata={
                        "order_id": order_id,
                        "user_id": user["id"],
                        "item_id": str(row_get(order, "servico_id") or order_id),
                        "item_title": item_title,
                        "item_description": item_description,
                        "category_id": "services",
                    },
                )
            except GatewayNotConfiguredError as exc:
                return jsonify({"error": str(exc), "code": exc.code}), exc.http_status
            except PaymentGatewayError as exc:
                return jsonify({"error": str(exc), "code": exc.code}), exc.http_status

            tx_status = intent_res.get("status") or "requires_action"
            gateway_payment_id = intent_res.get("gateway_payment_id")
            gateway_reference = intent_res.get("gateway_reference")
            checkout_url = intent_res.get("checkout_url")
            pix_qr_code = intent_res.get("pix_qr_code")
            pix_qr_base64 = intent_res.get("pix_qr_base64")
            boleto_barcode = intent_res.get("boleto_barcode")
            boleto_digitable_line = intent_res.get("boleto_digitable_line")
            boleto_url = intent_res.get("boleto_url")
            expires_at = intent_res.get("expires_at") or None

            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO payment_transactions (
                        public_id, order_id, user_id, gateway, method, status,
                        amount_cents, currency, gateway_payment_id, gateway_reference,
                        checkout_url, pix_qr_code, pix_qr_base64,
                        boleto_barcode, boleto_digitable_line, boleto_url,
                        payment_method_id, expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'BRL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        public_id,
                        order_id,
                        user["id"],
                        gateway,
                        method,
                        tx_status,
                        amount_cents,
                        gateway_payment_id,
                        gateway_reference,
                        checkout_url,
                        pix_qr_code,
                        pix_qr_base64,
                        boleto_barcode,
                        boleto_digitable_line,
                        boleto_url,
                        payment_method_id,
                        expires_at,
                    ),
                )
                payment_id = cursor.lastrowid
            except DBIntegrityError:
                conn.rollback()
                return jsonify({"error": "Transação duplicada detectada."}), 409

            resp_body = {
                "payment_id": public_id,
                "id": payment_id,
                "order_id": order_id,
                "gateway": gateway,
                "method": method,
                "status": tx_status,
                "amount_cents": amount_cents,
                "currency": "BRL",
                "checkout_url": checkout_url,
                "pix_qr_code": pix_qr_code,
                "pix_qr_base64": pix_qr_base64,
                "boleto_barcode": boleto_barcode,
                "boleto_digitable_line": boleto_digitable_line,
                "boleto_url": boleto_url,
                "expires_at": expires_at,
            }
            idem_race = save_idempotency(
                conn, user["id"], "create_intent", idempotency_key, req_hash, payment_id, 201, resp_body
            )
            if idem_race:
                race_state, race_payload = idem_race
                if race_state == "conflict":
                    return jsonify({"error": "Conflito de idempotência."}), 409
                return jsonify(race_payload[1]), race_payload[0]

            conn.commit()
            return jsonify(resp_body), 201
        finally:
            conn.close()

    @payments_bp.route("/api/payments/<payment_ref>/confirm", methods=["POST"])
    @rate_limit(20, 60)
    def confirm_payment_intent(payment_ref):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória.", "code": "UNAUTHORIZED"}), 401
        if user["tipo"] != "cliente":
            return jsonify({"error": "Apenas o cliente pode confirmar o pagamento."}), 403
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        idempotency_key = extract_idempotency_key(data)
        simulate_outcome = str(data.get("simulate_outcome") or "paid").strip().lower()
        if simulate_outcome not in ("paid", "failed"):
            simulate_outcome = "paid"

        conn = compat_get_db_connection()
        try:
            tx = lookup_payment_tx(conn, payment_ref)
            if not tx:
                return jsonify({"error": "Pagamento não encontrado."}), 404
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (tx["order_id"],)).fetchone()
            if not order or order["cliente_id"] != user["id"]:
                return jsonify({"error": "Pagamento não encontrado."}), 404

            if tx["gateway"] == "sandbox" and not is_sandbox_enabled():
                return jsonify({"error": "Gateway sandbox desabilitado em produção.", "code": "SANDBOX_DISABLED"}), 403

            req_hash = compute_request_hash(
                {
                    "payment_id": tx["id"],
                    "simulate_outcome": simulate_outcome if tx["gateway"] == "sandbox" else "live",
                }
            )
            idem_state, idem_payload = check_idempotency(conn, user["id"], "confirm_payment", idempotency_key, req_hash)
            if idem_state == "conflict":
                return jsonify(
                    {
                        "error": "Chave de idempotência reutilizada com parâmetros diferentes.",
                        "code": "IDEMPOTENCY_CONFLICT",
                    }
                ), 409
            if idem_state == "replay":
                return jsonify(idem_payload[1]), idem_payload[0]

            if tx["status"] in ("escrow_held", "released", "paid") or int(row_get(tx, "escrow_synced", 0) or 0) == 1:
                return jsonify({"error": "Pagamento já confirmado anteriormente."}), 409
            if tx["status"] in ("failed", "expired", "cancelled", "refunded", "partially_refunded"):
                return jsonify(
                    {"error": f"Pagamento em estado terminal '{tx['status']}' não pode ser confirmado."}
                ), 409

            adapter_factory = resolve_compat("app", "get_payment_adapter", get_payment_adapter)
            try:
                adapter = adapter_factory(tx["gateway"])
                res = adapter.confirm_intent(
                    gateway_payment_id=tx["gateway_payment_id"],
                    method=tx["method"],
                    simulate_outcome=simulate_outcome,
                    gateway_reference=row_get(tx, "gateway_reference"),
                    public_id=tx["public_id"],
                )
            except GatewayNotConfiguredError as exc:
                return jsonify({"error": str(exc), "code": exc.code}), exc.http_status
            except PaymentGatewayError as exc:
                return jsonify({"error": str(exc), "code": exc.code}), exc.http_status

            resolved_gw_pid = res.get("gateway_payment_id")
            resolved_gw_ref = res.get("gateway_reference")
            if resolved_gw_pid and resolved_gw_pid != row_get(tx, "gateway_payment_id"):
                fallback_ref = row_get(tx, "gateway_reference") or resolved_gw_ref or row_get(tx, "gateway_payment_id")
                conn.execute(
                    """
                    UPDATE payment_transactions
                    SET gateway_payment_id = ?, gateway_reference = COALESCE(gateway_reference, ?),
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (resolved_gw_pid, fallback_ref, tx["id"]),
                )

            gw_status = res.get("status") or tx["status"]
            if gw_status == "paid":
                ok, settle_info = settle_payment_and_sync_escrow(conn, tx, order)
                if not ok:
                    conn.rollback()
                    return jsonify({"error": settle_info}), 409
                resp_body = {
                    "payment_id": tx["public_id"],
                    "id": tx["id"],
                    "order_id": order["id"],
                    "status": settle_info["status"],
                    "escrow_status": settle_info["escrow_status"],
                    "pago": True,
                }
            elif gw_status in ("failed", "expired", "cancelled"):
                conn.execute(
                    """
                    UPDATE payment_transactions
                    SET status = ?, failure_code = ?, failure_message = ?, atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ? AND escrow_synced = 0
                """,
                    (gw_status, res.get("failure_code"), res.get("failure_message"), tx["id"]),
                )
                resp_body = {
                    "payment_id": tx["public_id"],
                    "id": tx["id"],
                    "order_id": order["id"],
                    "status": gw_status,
                    "escrow_status": row_get(order, "escrow_status", "pendente"),
                    "pago": False,
                }
            else:
                resp_body = {
                    "payment_id": tx["public_id"],
                    "id": tx["id"],
                    "order_id": order["id"],
                    "status": gw_status,
                    "escrow_status": row_get(order, "escrow_status", "pendente"),
                    "pago": bool(int(row_get(order, "pago", 0) or 0)),
                }

            idem_race = save_idempotency(
                conn, user["id"], "confirm_payment", idempotency_key, req_hash, tx["id"], 200, resp_body
            )
            if idem_race:
                race_state, race_payload = idem_race
                if race_state == "conflict":
                    return jsonify({"error": "Conflito de idempotência."}), 409
                return jsonify(race_payload[1]), race_payload[0]

            conn.commit()
            return jsonify(resp_body), 200
        finally:
            conn.close()
