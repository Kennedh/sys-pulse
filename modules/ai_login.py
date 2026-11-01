import base64
import hashlib
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from modules.ai_service import request_json


class BrowserLogin:
    def __init__(self):
        self.verifier = secrets.token_urlsafe(48)
        self.callback_path = "/syspulse/" + secrets.token_urlsafe(24)
        self.code = None
        self.denied = False
        self.closed = False
        login = self

        class Callback(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(1)
                super().setup()

            def log_message(self, *_):
                pass

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if self.headers.get("Host") != login.host or parsed.path != login.callback_path:
                    self.send_error(404)
                    return
                try:
                    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, max_num_fields=8)
                except ValueError:
                    self.send_error(400)
                    return
                codes = query.get("code", [])
                if "error" in query:
                    login.denied = True
                elif len(codes) == 1 and 1 <= len(codes[0]) <= 2048 and not login.code:
                    login.code = codes[0]
                else:
                    self.send_error(400)
                    return
                body = "Autorização recebida. Volte ao SysPulse para conferir a conexão.".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), Callback)
        self.server.timeout = .2
        self.host = "localhost:" + str(self.server.server_port)
        self.callback = "http://" + self.host + self.callback_path
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        self.url = "https://openrouter.ai/auth?" + urllib.parse.urlencode({
            "callback_url": self.callback, "code_challenge": challenge, "code_challenge_method": "S256"})

    def wait(self, cancelled=lambda: False, timeout=180):
        deadline = time.monotonic() + timeout
        try:
            while not self.code and not self.denied:
                if self.closed or cancelled():
                    raise RuntimeError("Conexão cancelada.")
                if time.monotonic() >= deadline:
                    raise RuntimeError("O tempo de autorização terminou. Tente conectar novamente.")
                self.server.handle_request()
            if self.denied:
                raise RuntimeError("Autorização recusada no OpenRouter. A seleção anterior continua disponível.")
            if cancelled():
                raise RuntimeError("Conexão cancelada.")
            response = request_json("https://openrouter.ai/api/v1/auth/keys", body={
                "code": self.code, "code_verifier": self.verifier, "code_challenge_method": "S256"},
                timeout=20, limit=16384)
            key = response.get("key") if isinstance(response, dict) else None
            if not isinstance(key, str) or not 16 <= len(key) <= 2048 or any(char.isspace() for char in key):
                raise ValueError("O serviço não confirmou uma credencial válida.")
            return key
        finally:
            self.close()
            self.verifier = ""
            self.code = None

    def close(self):
        if not self.closed:
            self.closed = True
            self.server.server_close()
