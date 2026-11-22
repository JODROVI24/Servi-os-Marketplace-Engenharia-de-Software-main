"""Testes de verificação estrutural para as entregas da Fase 4 (CI, deps, deploy e SEO)."""

import glob
import json
import os
import re
import tomllib
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(REPO_ROOT, "public")


class TestPhase4Deliverables(unittest.TestCase):
    """Valida dependências, CI/Dependabot, deploy Vercel, README e SEO canônico."""

    def test_dependencies_and_lockfile(self):
        pyproject_path = os.path.join(REPO_ROOT, "pyproject.toml")
        uv_lock_path = os.path.join(REPO_ROOT, "uv.lock")
        req_path = os.path.join(REPO_ROOT, "requirements.txt")
        req_dev_path = os.path.join(REPO_ROOT, "requirements-dev.txt")
        legacy_api_req = os.path.join(REPO_ROOT, "api", "requirements.txt")

        self.assertTrue(os.path.isfile(pyproject_path))
        self.assertTrue(os.path.isfile(uv_lock_path))
        self.assertFalse(os.path.exists(legacy_api_req), "api/requirements.txt deve permanecer unificado e removido")

        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        self.assertEqual(data["project"]["name"], "pertoja-marketplace")
        self.assertFalse(data["tool"]["uv"]["package"])
        self.assertGreaterEqual(data["tool"]["coverage"]["report"]["fail_under"], 80)

        for path in (req_path, req_dev_path):
            with open(path, "r", encoding="utf-8") as f:
                pkg_lines = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("-r")
                ]
            self.assertGreater(len(pkg_lines), 0)
            for pkg_line in pkg_lines:
                self.assertIn("==", pkg_line, f"Dependência não fixada em {path}: {pkg_line}")

    def test_ci_workflow_and_dependabot(self):
        dep_path = os.path.join(REPO_ROOT, ".github", "dependabot.yml")
        ci_path = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")

        self.assertTrue(os.path.isfile(dep_path))
        with open(dep_path, "r", encoding="utf-8") as f:
            dep_content = f.read()
        for eco in ('"pip"', '"npm"', '"github-actions"'):
            self.assertIn(eco, dep_content)

        self.assertTrue(os.path.isfile(ci_path))
        with open(ci_path, "r", encoding="utf-8") as f:
            ci_content = f.read()
        for expected in (
            "ruff check .",
            "ruff format --check .",
            "pytest --cov --cov-fail-under=80",
            "npm run lint:js",
            "npm run test:routing",
            "pip-audit",
            "npm audit",
        ):
            self.assertIn(expected, ci_content)

    def test_vercel_include_files_and_vercelignore(self):
        vercel_path = os.path.join(REPO_ROOT, "vercel.json")
        ignore_path = os.path.join(REPO_ROOT, ".vercelignore")

        with open(vercel_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        include_files = cfg["functions"]["api/index.py"]["includeFiles"]
        self.assertNotEqual(include_files, "**")
        self.assertIn("app.py", include_files)
        self.assertIn("database.py", include_files)
        self.assertIn("scripts/migrations/**", include_files)

        expanded = include_files.strip("{}").split(",")
        for entry in expanded:
            entry = entry.strip()
            if "*" in entry:
                matches = glob.glob(os.path.join(REPO_ROOT, entry), recursive=True)
                self.assertGreater(len(matches), 0, f"Nenhum arquivo encontrado para glob {entry}")
            else:
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, entry)), f"Arquivo ausente: {entry}")

        with open(ignore_path, "r", encoding="utf-8") as f:
            ignore_lines = {line.strip() for line in f if line.strip() and not line.strip().startswith("#")}
        for required_ignored in ("tests/", "docs/", "node_modules/", ".venv/"):
            self.assertIn(required_ignored, ignore_lines)
        for must_not_ignore in ("src/", "package.json", "pyproject.toml", "requirements.txt", "tailwind.config.js"):
            self.assertNotIn(must_not_ignore, ignore_lines)

    def test_readme_updated_without_pillow_and_with_production_postgres(self):
        readme_path = os.path.join(REPO_ROOT, "README.md")
        with open(readme_path, "r", encoding="utf-8") as f:
            readme = f.read()
        self.assertNotIn("Pillow", readme)
        self.assertIn("PostgreSQL", readme)
        self.assertIn("SECRET_KEY", readme)
        self.assertIn("DATABASE_URL", readme)
        self.assertIn("## 🛡️ Arquitetura, Performance e Melhorias Implementadas", readme)
        self.assertNotIn("---\n\n1. **Correção de Falhas Críticas:**", readme)

    def test_seo_canonical_og_url_and_unique_og_images(self):
        indexable_pages = (
            "index.html",
            "pedido.html",
            "como-funciona.html",
            "sobre-nos.html",
            "cadastro.html",
            "login.html",
            "termos.html",
            "privacidade.html",
        )
        noindex_pages = ("portal-cliente.html", "portal-prestador.html")

        seen_og_images = {}
        canonical_re = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"')
        og_url_re = re.compile(r'<meta\s+property="og:url"\s+content="([^"]+)"')
        og_img_re = re.compile(r'<meta\s+property="og:image"\s+content="([^"]+)"')

        for page in indexable_pages + noindex_pages:
            path = os.path.join(PUBLIC_DIR, page)
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()

            m_canon = canonical_re.search(html)
            self.assertIsNotNone(m_canon, f"canonical ausente em {page}")
            canon_url = m_canon.group(1)
            self.assertTrue(canon_url.startswith("https://pertoja.com.br/"))
            self.assertFalse(canon_url.endswith(".html"), f"canonical com .html em {page}: {canon_url}")
            self.assertNotIn("/index.html", canon_url)

            if page in indexable_pages:
                m_og_url = og_url_re.search(html)
                self.assertIsNotNone(m_og_url, f"og:url ausente em {page}")
                self.assertEqual(m_og_url.group(1), canon_url)

                m_og_img = og_img_re.search(html)
                self.assertIsNotNone(m_og_img, f"og:image ausente em {page}")
                og_img_url = m_og_img.group(1)
                self.assertTrue(og_img_url.startswith("https://pertoja.com.br/img/"))
                rel_img = og_img_url.removeprefix("https://pertoja.com.br/")
                self.assertTrue(
                    os.path.isfile(os.path.join(PUBLIC_DIR, rel_img)),
                    f"Imagem OG inexistente para {page}: {rel_img}",
                )
                self.assertNotIn(
                    og_img_url,
                    seen_og_images,
                    f"og:image duplicada entre {page} e {seen_og_images.get(og_img_url)}: {og_img_url}",
                )
                seen_og_images[og_img_url] = page

        with open(os.path.join(PUBLIC_DIR, "sitemap.xml"), "r", encoding="utf-8") as f:
            sitemap = f.read()
        self.assertNotIn("https://pertoja.com.br/index.html", sitemap)
        self.assertIn("https://pertoja.com.br/", sitemap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
