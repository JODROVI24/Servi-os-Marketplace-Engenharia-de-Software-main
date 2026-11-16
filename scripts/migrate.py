"""
CLI para execução e inspeção de migrations SQL versionadas (scripts/migrations/*.sql).

Uso:
    python -m scripts.migrate [--dry-run]
"""

import argparse
import sys
import database


def main(argv=None):
    parser = argparse.ArgumentParser(description="Executa migrations do PertoJá Marketplace.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula a execução listando migrations pendentes sem alterar o banco."
    )
    args = parser.parse_args(argv)

    engine = database.get_active_engine()
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"=== PertoJá Migrations ({mode}) ===")
    print(f"Engine: {engine}")
    if engine == "sqlite":
        print(f"SQLite Path: {database.DB_PATH}")

    report = database.run_migrations(dry_run=args.dry_run)
    if not report:
        print("Nenhuma migration encontrada em scripts/migrations/.")
        return 0

    for item in report:
        print(f"  [{item['status'].upper()}] {item['version']}")

    applied_count = sum(1 for r in report if r['status'] == 'applied')
    pending_count = sum(1 for r in report if r['status'] == 'pending')
    already_count = sum(1 for r in report if r['status'] == 'already_applied')
    print(
        f"Resumo: total={len(report)}, aplicadas={applied_count}, "
        f"pendentes={pending_count}, ja_aplicadas={already_count}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
