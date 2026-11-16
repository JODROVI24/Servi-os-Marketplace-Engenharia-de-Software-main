@echo off
REM Loop de melhoria automática do repositório PertoJá Marketplace.
REM Executa testes e gera reports/last-run.md.
cd /d "%~dp0\..
if not exist .venv\Scripts\python.exe (
    echo [ERRO] virtualenv (.venv) não encontrado. Crie com:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt pytest python-dotenv gunicorn
    exit /b 1
)
.venv\Scripts\python.exe scripts\run-improvement-loop.py %*
