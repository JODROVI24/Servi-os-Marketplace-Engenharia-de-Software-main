from flask.testing import FlaskClient
from werkzeug.datastructures import Headers


class BrowserCSRFTestClient(FlaskClient):
    """Cliente de teste que simula navegação same-origin enviando Origin e X-CSRF-Token."""

    def open(self, *args, **kwargs):
        method = str(kwargs.get("method") or "GET").upper()
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            headers = Headers(kwargs.get("headers"))
            if "Origin" not in headers and "Referer" not in headers:
                headers["Origin"] = "http://localhost"
            if "X-CSRF-Token" not in headers:
                csrf_cookie = self.get_cookie("csrf_token")
                if csrf_cookie and csrf_cookie.value:
                    headers["X-CSRF-Token"] = csrf_cookie.value
            kwargs["headers"] = headers
        return super().open(*args, **kwargs)
