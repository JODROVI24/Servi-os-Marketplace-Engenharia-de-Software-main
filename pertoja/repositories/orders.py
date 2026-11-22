"""Repositório de pedidos e consultas associadas."""


def get_order_by_id(conn, order_id: int):
    """Busca pedido pelo identificador primário."""
    return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def get_order_with_details(conn, order_id: int):
    """Busca pedido com dados básicos do serviço e participantes."""
    return conn.execute(
        """
        SELECT o.*,
               s.titulo AS servico_titulo,
               s.categoria AS servico_categoria,
               c.nome AS cliente_nome,
               p.nome AS prestador_nome
        FROM orders o
        LEFT JOIN services s ON o.servico_id = s.id
        LEFT JOIN users c ON o.cliente_id = c.id
        LEFT JOIN users p ON o.prestador_id = p.id
        WHERE o.id = ?
        """,
        (order_id,),
    ).fetchone()


def get_order_by_share_token(conn, share_token: str):
    """Busca pedido associado a um token público de compartilhamento de rota."""
    return conn.execute(
        """
        SELECT o.*,
               p.nome AS prestador_nome,
               p.lat AS prestador_lat,
               p.lng AS prestador_lng,
               p.bairro AS prestador_bairro,
               p.cidade AS prestador_cidade,
               s.titulo AS servico_titulo
        FROM orders o
        JOIN users p ON o.prestador_id = p.id
        JOIN services s ON o.servico_id = s.id
        WHERE o.share_token = ?
        """,
        (share_token,),
    ).fetchone()


def get_order_recent_summaries(conn, user_id: int, limit: int = 3) -> list[dict[str, object]]:
    """Lista resumo não-PII dos últimos pedidos de um usuário autenticado."""
    rows = conn.execute(
        """
        SELECT
            o.id AS id,
            o.status AS status,
            o.escrow_status AS escrow_status,
            COALESCE(s.titulo, 'Serviço') AS servico_titulo
        FROM orders o
        LEFT JOIN services s ON o.servico_id = s.id
        WHERE o.cliente_id = ? OR o.prestador_id = ?
        ORDER BY o.criado_em DESC, o.id DESC
        LIMIT ?
        """,
        (user_id, user_id, int(limit)),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "status": r["status"],
            "escrow_status": r["escrow_status"],
            "servico_titulo": r["servico_titulo"] or "Serviço",
        }
        for r in rows
    ]
