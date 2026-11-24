"""Sincronização de dados de seed de demonstração em desenvolvimento local."""

from werkzeug.security import generate_password_hash

from pertoja._compat import resolve_compat
from pertoja.db.connection import is_demo_seed_enabled, is_production_env
from pertoja.db.seed_data import PRESTADORES_SEED_35


def sincronizar_todos_prestadores(conn) -> None:
    """Insere prestadores e serviços de demonstração quando ENABLE_DEMO_SEED=1 fora de produção."""
    if is_production_env():
        return
    demo_enabled_fn = resolve_compat("database", "is_demo_seed_enabled", is_demo_seed_enabled)
    if not demo_enabled_fn():
        return
    cursor = conn.cursor()

    count_row = cursor.execute("SELECT COUNT(*) FROM users WHERE tipo = 'prestador'").fetchone()
    if count_row is not None:
        try:
            count = count_row[0]
        except (IndexError, TypeError):
            count = getattr(count_row, "count", 0)
        if count >= 35:
            return

    pwd_hash = generate_password_hash("123456")

    for (
        nome,
        email,
        tel,
        bio,
        cat,
        s_titulo,
        preco,
        rating,
        cep,
        end,
        num,
        bairro,
        cid,
        uf,
        lat,
        lng,
        disp,
    ) in PRESTADORES_SEED_35:
        kyc_tier_seed = 2 if cat in ("Elétrica", "Encanamento") else 1
        reg_prof_seed = "CFT/CREA-SEED" if cat in ("Elétrica", "Encanamento") else None
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                """
                INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng, avaliacao_media, total_avaliacoes, disponivel, kyc_tier, kyc_status, registro_profissional, status_conta)
                VALUES (?, ?, ?, 'prestador', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 15, ?, ?, 'aprovado', ?, 'ativo')
            """,
                (
                    nome,
                    email,
                    pwd_hash,
                    tel,
                    bio,
                    cep,
                    end,
                    num,
                    bairro,
                    cid,
                    uf,
                    lat,
                    lng,
                    rating,
                    disp,
                    kyc_tier_seed,
                    reg_prof_seed,
                ),
            )
            p_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
                (p_id, s_titulo, bio, cat, preco, cep, end, num, bairro, cid, uf, lat, lng),
            )
        else:
            p_id = row["id"]
            has_service = cursor.execute("SELECT 1 FROM services WHERE prestador_id = ? LIMIT 1", (p_id,)).fetchone()
            if not has_service:
                cursor.execute(
                    """
                    INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                    (p_id, s_titulo, bio, cat, preco, cep, end, num, bairro, cid, uf, lat, lng),
                )
    conn.commit()
