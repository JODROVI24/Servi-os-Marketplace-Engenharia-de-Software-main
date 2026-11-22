"""Blueprint de páginas estáticas, handlers de erro, health check e geocodificação."""

import os
import re
import sqlite3
import time

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from pertoja._compat import resolve_compat
from pertoja.config import ALLOWED_STATIC_EXTENSIONS, PUBLIC_DIR
from pertoja.db.connection import PG_DB_ERRORS, get_active_engine
from pertoja.extensions import compat_get_db_connection, rate_limit
from pertoja.services.geo import geocode_address, lookup_cep_and_coords

pages_bp = Blueprint("pages", __name__)


def _not_found_response():
    """Retorna 404.html se existir em PUBLIC_DIR, senão JSON 404."""
    page_404 = os.path.join(PUBLIC_DIR, "404.html")
    if os.path.isfile(page_404):
        return send_from_directory(PUBLIC_DIR, "404.html"), 404
    return jsonify({"error": "Página não encontrada."}), 404


def handle_404(_err):
    """Handler HTTP 404 diferenciado para rotas da API e páginas estáticas."""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint da API não encontrado."}), 404
    return _not_found_response()


def handle_500(err):
    """Handler HTTP 500 que registra contexto estruturado sem expor traceback."""
    current_app.logger.error(
        "Erro interno não tratado na requisição.",
        extra={"event": "http_500", "path": request.path, "error_type": type(err).__name__},
    )
    if request.path.startswith("/api/"):
        return jsonify({"error": "Erro interno do servidor."}), 500
    if os.path.isfile(os.path.join(PUBLIC_DIR, "404.html")):
        return send_from_directory(PUBLIC_DIR, "404.html"), 500
    return jsonify({"error": "Erro interno do servidor."}), 500


@pages_bp.route("/")
def home():
    """Serve a página inicial do marketplace."""
    return send_from_directory(PUBLIC_DIR, "index.html")


@pages_bp.route("/robots.txt")
def robots():
    """Serve robots.txt para rastreadores."""
    return send_from_directory(PUBLIC_DIR, "robots.txt", mimetype="text/plain")


@pages_bp.route("/sitemap.xml")
def sitemap():
    """Serve sitemap.xml canônico."""
    return send_from_directory(PUBLIC_DIR, "sitemap.xml", mimetype="application/xml")


@pages_bp.route("/manifest.json")
def manifest():
    """Serve manifest PWA."""
    return send_from_directory(PUBLIC_DIR, "manifest.json", mimetype="application/manifest+json")


@pages_bp.route("/termos")
@pages_bp.route("/termos.html")
def termos_page():
    """Serve os Termos de Uso."""
    return send_from_directory(PUBLIC_DIR, "termos.html")


@pages_bp.route("/privacidade")
@pages_bp.route("/privacidade.html")
def privacidade_page():
    """Serve a Política de Privacidade."""
    return send_from_directory(PUBLIC_DIR, "privacidade.html")


@pages_bp.route("/<path:filename>")
def serve_static(filename):
    """Serve arquivos estáticos permitidos e URLs amigáveis com proteção contra path traversal."""
    clean_req = filename.lstrip("/")
    if clean_req == "api" or clean_req.startswith("api/"):
        return jsonify({"error": "Endpoint da API não encontrado."}), 404

    if clean_req in ("", "index", "home"):
        return send_from_directory(PUBLIC_DIR, "index.html")

    static_root = os.path.abspath(PUBLIC_DIR)
    normalized_rel = os.path.normpath(clean_req)
    if normalized_rel.startswith("..") or os.path.isabs(normalized_rel):
        return _not_found_response()

    target_path = os.path.abspath(os.path.join(static_root, normalized_rel))
    if not (target_path == static_root or target_path.startswith(static_root + os.sep)):
        return _not_found_response()

    if os.path.isfile(target_path):
        ext = os.path.splitext(target_path)[1].lower()
        if ext in ALLOWED_STATIC_EXTENSIONS:
            return send_from_directory(static_root, normalized_rel.replace("\\", "/"))
        return _not_found_response()

    if not os.path.splitext(normalized_rel)[1]:
        html_rel = normalized_rel + ".html"
        html_target = os.path.abspath(os.path.join(static_root, html_rel))
        if html_target.startswith(static_root + os.sep) and os.path.isfile(html_target):
            return send_from_directory(static_root, html_rel.replace("\\", "/"))

    return _not_found_response()


@pages_bp.route("/api/health", methods=["GET"])
def health_check():
    """Verifica disponibilidade da aplicação e conectividade com o banco ativo."""
    engine = resolve_compat("database", "get_active_engine", get_active_engine)()
    status = {
        "status": "healthy",
        "timestamp": time.time(),
        "database": "connected",
        "engine": engine,
        "version": "2.0.0",
        "environment": "vercel" if os.environ.get("VERCEL") == "1" else "standalone",
    }
    try:
        conn = compat_get_db_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except (sqlite3.Error, RuntimeError, ValueError, OSError, *PG_DB_ERRORS) as err:
        current_app.logger.error(
            "Falha de conexão no health check de banco de dados.",
            extra={"event": "health_check_db_error", "error_type": type(err).__name__},
        )
        status["status"] = "degraded"
        status["database"] = "unavailable"
        return jsonify(status), 503
    return jsonify(status), 200


@pages_bp.route("/api/cep/<cep>", methods=["GET"])
@rate_limit(200, 60)
def consultar_cep(cep):
    """Consulta dados de CEP via ViaCEP/BrasilAPI e enriquece com geocodificação."""
    clean_cep = re.sub(r"\D", "", cep)
    if len(clean_cep) != 8:
        return jsonify({"error": "CEP inválido. Deve conter 8 dígitos numéricos."}), 400

    data = lookup_cep_and_coords(clean_cep)
    if not data:
        return jsonify({"error": "CEP não encontrado na base oficial dos Correios."}), 404
    return jsonify(data)


@pages_bp.route("/api/geocode", methods=["GET"])
@rate_limit(60, 60)
def geocode_endpoint():
    """Geocodifica endereço textual usando Nominatim com cache em banco."""
    query = request.args.get("address") or request.args.get("q") or ""
    street = (request.args.get("street") or "").strip() or None
    neighborhood = (request.args.get("neighborhood") or "").strip() or None
    city = (request.args.get("city") or "").strip() or None
    state = (request.args.get("state") or "").strip() or None
    if not query.strip() and not any([street, neighborhood, city, state]):
        return jsonify({"error": "Parâmetro de endereço obrigatório."}), 400
    lat, lng = geocode_address(query.strip(), street=street, neighborhood=neighborhood, city=city, state=state)
    if lat is None or lng is None:
        return jsonify({"error": "Endereço não localizado no mapa.", "lat": None, "lng": None}), 404
    return jsonify({"lat": lat, "lng": lng, "query": query.strip()})
