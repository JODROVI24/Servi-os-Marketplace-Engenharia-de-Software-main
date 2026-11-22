"""Repositório de serviços ofertados pelos prestadores."""


def get_service_by_id(conn, service_id: int):
    """Busca serviço específico pelo ID."""
    return conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()


def list_provider_services(conn, provider_id: int):
    """Lista serviços cadastrados por um prestador ordenados por data de criação."""
    return conn.execute(
        "SELECT * FROM services WHERE prestador_id = ? ORDER BY criado_em DESC",
        (provider_id,),
    ).fetchall()
