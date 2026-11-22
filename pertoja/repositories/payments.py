"""Repositório de métodos salvos e transações de pagamento."""


def find_payment_by_ref(conn, payment_ref: str):
    """Localiza transação de pagamento por public_id ou identificador numérico."""
    ref = str(payment_ref or "").strip()
    if ref.isdigit():
        return conn.execute(
            "SELECT * FROM payment_transactions WHERE public_id = ? OR id = ?",
            (ref, int(ref)),
        ).fetchone()
    return conn.execute("SELECT * FROM payment_transactions WHERE public_id = ?", (ref,)).fetchone()


def find_payment_for_order(conn, order_id: int):
    """Retorna a transação de pagamento mais recente de um pedido."""
    return conn.execute(
        "SELECT * FROM payment_transactions WHERE order_id = ? ORDER BY id DESC LIMIT 1",
        (order_id,),
    ).fetchone()


def list_payments_for_order(conn, order_id: int):
    """Lista todas as transações de pagamento associadas a um pedido."""
    return conn.execute(
        "SELECT * FROM payment_transactions WHERE order_id = ? ORDER BY id DESC",
        (order_id,),
    ).fetchall()


def list_active_payment_methods(conn, user_id: int):
    """Lista cartões tokenizados ativos do usuário ordenados por padrão e criação."""
    return conn.execute(
        """
        SELECT public_id, gateway, brand, last4, exp_month, exp_year, holder_label, is_default, criado_em
        FROM payment_methods
        WHERE user_id = ? AND active = 1
        ORDER BY is_default DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
