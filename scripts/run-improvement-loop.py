#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loop de melhoria automática do repositório PertoJá Marketplace.

Uso:
    python scripts/run-improvement-loop.py            # loop completo
    python scripts/run-improvement-loop.py init       # garante pastas de suporte

O loop:
  1. Lê o estado atual do git (branch, commits, limpo ou não).
  2. Roda os testes de qualidade (vetores de ambiente locais e VERCEL=1).
  3. Gera reports/last-run.md com o resultado.
  4. Imprime um resumo na tela para interceptar.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = sys.executable
REPORT = os.path.join(REPO_ROOT, "reports", "loop.log")
LOG = os.path.join(REPO_ROOT, "reports", "loop.log")


def get_report_path():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(REPO_ROOT, "reports", f"last-run-{ts}.md")


def run_git_head():
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def git_diff_summary(prev, head):
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-status", prev, head],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return [line for line in proc.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []


def load_state():
    path = os.path.join(REPO_ROOT, "reports", ".git-state.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    path = os.path.join(REPO_ROOT, "reports", ".git-state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def run(cmd, cwd=REPO_ROOT, check=False):
    print(f"\n+ {cmd}")
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if proc.stdout:
        print(proc.stdout[-4000:])
    if proc.stderr:
        print("[stderr]", proc.stderr[-2000:])
    return proc.stdout


def env_config(name):
    return {
        "REPO_ROOT": REPO_ROOT,
        "TERM": "dumb",
        "VERCEL": "1",
        "PYTHONUNBUFFERED": "1",
        **os.environ,
    }


def git_state():
    return {
        "branch": run("git branch --show-current", check=True),
        "commits": run("git rev-list --count HEAD", check=True),
        "clean": run("git status --porcelain", check=True),
    }


def run_status(cmd):
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        shell=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if proc.stdout:
        print(proc.stdout[-4000:])
    if proc.stderr:
        print("[stderr]", proc.stderr[-2000:])
    return proc.returncode, proc.stdout


def run_tests():
    py = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
    codes = {}
    codes["root_suit"] = run_status(f"{py} -m unittest discover -s tests -v")[0]
    codes["api_import"] = run_status(f'"{py}" -c "import api.index; print(\'OK entrypoint Vercel\')"')[0]
    return codes


def write_report(results, env):
    report_file = get_report_path()
    ts = datetime.now(timezone.utc).isoformat()
    lines = []
    lines.append("=" * 72)
    lines.append("IMPROVEMENT LOOP REPORT — PertoJá Marketplace")
    lines.append(f"Gerado em: {ts}")
    lines.append(f"Repo: {REPO_ROOT}")
    lines.append("=" * 72)
    lines.append("\n## Git state")
    for k, v in env.items():
        lines.append(f"- **{k}**: {v.strip()}")
    lines.append("\n## Test results")
    for k, v in results.items():
        ok = v == 0
        lines.append(f"- **{k}**: {'PASS' if ok else 'FAIL'} (exit {v})")
    lines.append("\n## Git changes since last run")
    lines.append("\n## Git changes since last run")
    state = load_state()
    head = run_git_head()
    if state.get("head") and state.get("head") != head:
        lines.append(f"- **Commits**: {head[:8]} (antes era {state['head'][:8]})")
        changed = git_diff_summary(state["head"], head)
        if changed:
            for item in changed:
                lines.append(f"- {item}")
        else:
            lines.append("- (sem mudanças de arquivo)")
    else:
        lines.append("- (run inicial / sem hash anterior)")
    if head:
        lines.append(f"- **HEAD atual**: {head[:10]}")
    save_state({"head": head, "at": ts})
    lines.append("\n## Trending")
    lines.append("- T-001..T-003: orquestração de ordens para o Argon (docs/IMPROVEMENT_BOARD.md).")
    lines.append("- T-004..T-012: melhorias de código, fechamento viciante, cache, SQL, segurança.")
    lines.append("\n## Conclusion")
    all_pass = all(v == 0 for v in results.values())
    lines.append("És passinhos? " + ("✅ Todos os testes passaram." if all_pass else "❌ Alguns testes falharam."))
    lines.append("")
    os.makedirs(os.path.dirname(report_file), exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"\n=== {ts} ===\n" + "\n".join(lines))


def main():
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        os.makedirs(REPO_ROOT, exist_ok=True)
        for folder in ("reports", "scripts"):
            os.makedirs(os.path.join(REPO_ROOT, folder), exist_ok=True)
        print("diretórios prontos:", os.path.join(REPO_ROOT, "reports"))
        return

    state = git_state()
    results = run_tests()
    write_report(results, state)
    print("\n" + "=" * 72)
    print("RELATÓRIO GRAVADO EM:", REPORT)
    print("Saída no console será lida no log: reports/loop.log")


if __name__ == "__main__":
    main()
