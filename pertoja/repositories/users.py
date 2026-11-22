"""Repositório de usuários, perfis e versionamento de sessão."""


def find_user_by_id(conn, user_id: int):
    """Retorna o registro completo de usuário pelo ID ou None."""
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def find_user_by_email(conn, email: str):
    """Retorna usuário buscando por e-mail normalizado em minúsculas."""
    clean_email = (email or "").strip().lower()
    if not clean_email:
        return None
    return conn.execute("SELECT * FROM users WHERE LOWER(email) = ?", (clean_email,)).fetchone()


def increment_session_version(conn, user_id: int) -> None:
    """Invalida sessões ativas do usuário incrementando session_version."""
    conn.execute(
        "UPDATE users SET session_version = COALESCE(session_version, 1) + 1 WHERE id = ?",
        (user_id,),
    )
