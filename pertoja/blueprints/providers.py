"""Blueprint de visão financeira e serviços do prestador autenticado."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from pertoja.extensions import (
    compat_get_db_connection,
    get_current_user,
    parse_dt,
    row_get,
)

providers_bp = Blueprint("providers", __name__)


@providers_bp.route("/api/my-services", methods=["GET"])
def my_services():
    """Lista os serviços pertencentes ao prestador autenticado."""
    user = get_current_user()
    if not user or user["tipo"] != "prestador":
        return jsonify({"error": "Acesso exclusivo para prestadores de serviço."}), 403

    conn = compat_get_db_connection()
    include_all = request.args.get("all", "0") == "1"
    if include_all:
        services = conn.execute(
            "SELECT * FROM services WHERE prestador_id = ? ORDER BY criado_em DESC",
            (user["id"],),
        ).fetchall()
    else:
        services = conn.execute(
            "SELECT * FROM services WHERE prestador_id = ? AND ativo = 1 ORDER BY criado_em DESC",
            (user["id"],),
        ).fetchall()
    conn.close()

    return jsonify([dict(s) for s in services])


@providers_bp.route("/api/provider/financial-summary", methods=["GET"])
def provider_financial_summary():
    """Calcula faturamento mensal, saldo retido em Escrow e taxas conforme plano."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória."}), 401
    if user["tipo"] != "prestador":
        return jsonify({"error": "Acesso exclusivo para prestadores."}), 403

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    current_ym = now_utc.strftime("%Y-%m")
    plano = row_get(user, "plano", "basico")
    taxa_percentual = 0.08 if plano == "pro" else 0.12

    conn = compat_get_db_connection()
    try:
        orders = conn.execute(
            """
            SELECT status, pago, preco_total, escrow_status, release_due_at, criado_em, completed_at
            FROM orders
            WHERE prestador_id = ?
        """,
            (user["id"],),
        ).fetchall()
    finally:
        conn.close()

    faturamento_bruto_mes = 0.0
    saldo_escrow_retido = 0.0
    escrow_aguardando_48h = 0.0
    total_liberado = 0.0

    for o in orders:
        preco = float(row_get(o, "preco_total", 0.0) or 0.0)
        status = row_get(o, "status", "")
        pago = int(row_get(o, "pago", 0) or 0)
        escrow_st = row_get(o, "escrow_status", "pendente")
        ref_dt = str(row_get(o, "completed_at") or row_get(o, "criado_em") or "")

        if status == "finalizado" and pago == 1:
            if ref_dt.startswith(current_ym):
                faturamento_bruto_mes += preco
            if escrow_st == "liberado":
                total_liberado += preco
            elif escrow_st == "aguardando_liberacao":
                due_dt = parse_dt(row_get(o, "release_due_at"))
                if due_dt is not None and due_dt <= now_utc:
                    total_liberado += preco
                else:
                    saldo_escrow_retido += preco
                    escrow_aguardando_48h += preco
            else:
                saldo_escrow_retido += preco
        elif (
            pago == 1
            and status not in ("finalizado", "cancelado")
            and escrow_st not in ("estornado_total", "estornado_parcial")
        ):
            saldo_escrow_retido += preco

    faturamento_bruto_mes = round(faturamento_bruto_mes, 2)
    saldo_escrow_retido = round(saldo_escrow_retido, 2)
    escrow_aguardando_48h = round(escrow_aguardando_48h, 2)
    total_liberado = round(total_liberado, 2)
    total_liberado_liquido = round(total_liberado * (1.0 - taxa_percentual), 2)
    isento_mensalidade = plano == "basico" and faturamento_bruto_mes <= 1800.0

    return jsonify(
        {
            "mes_referencia": current_ym,
            "plano": plano,
            "taxa_percentual": taxa_percentual,
            "faturamento_bruto_mes": faturamento_bruto_mes,
            "isento_mensalidade": isento_mensalidade,
            "saldo_escrow_retido": saldo_escrow_retido,
            "escrow_aguardando_48h": escrow_aguardando_48h,
            "total_liberado": total_liberado,
            "total_liberado_liquido": total_liberado_liquido,
        }
    ), 200
