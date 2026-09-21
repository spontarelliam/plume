"""
Tests for the InvenTree diagnostics. No FreeCAD needed:

    python -m unittest discover -s tests
"""
import base64
import importlib.util
import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "plume")

# FreeCAD puts freecad/plume on sys.path, and the bundled 'inventree' client relies on it
sys.path.insert(0, os.path.abspath(ROOT))

spec = importlib.util.spec_from_file_location("inventree_check", os.path.join(ROOT, "utils", "inventree_check.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class FakeServer(BaseHTTPRequestHandler):
    """Pretends to be an InvenTree server. Behaviour is set by class attributes."""

    api_root = (200, {"server": "InvenTree", "apiVersion": 300})
    user = "admin"
    password = "secret"
    token = "tok"

    def log_message(self, *args):
        pass

    def _send(self, status, body):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/":
            status, body = self.api_root
            self._send(status, body)
        elif self.path == "/api/user/me/":
            header = self.headers.get("Authorization", "")
            expected = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            tok = self.headers.get("AUTHORIZATION", "")
            if header == expected or tok == f"Token {self.token}":
                self._send(200, {"username": self.user})
            else:
                self._send(401, {"detail": "no"})
        else:
            self._send(404, {})


def make_handler(**attrs):
    return type("Handler", (FakeServer,), attrs)


class Server:
    def __init__(self, **attrs):
        self.httpd = HTTPServer(("127.0.0.1", 0), make_handler(**attrs))
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestBaseUrl(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(check.base_url("http://host:8000"), "http://host:8000/")
        self.assertEqual(check.base_url("https://host/inventree/api/"), "https://host/inventree/")

    def test_invalid(self):
        for url in ["", "host:8000", "ftp://host", "http://", "just text"]:
            self.assertIsNone(check.base_url(url), url)


class TestDiagnose(unittest.TestCase):
    def test_no_url(self):
        self.assertEqual(check.diagnose_inventree("").code, "no_url")
        self.assertEqual(check.diagnose_inventree(None).code, "no_url")
        self.assertEqual(check.diagnose_inventree("   ").code, "no_url")

    def test_bad_url(self):
        self.assertEqual(check.diagnose_inventree("localhost:8000").code, "bad_url")

    def test_unreachable(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listens on this port any more
        self.assertEqual(check.diagnose_inventree(f"http://127.0.0.1:{port}").code, "unreachable")

    def test_not_found(self):
        with Server(api_root=(404, {})) as s:
            self.assertEqual(check.diagnose_inventree(s.url).code, "server_error")

    def test_not_json(self):
        with Server(api_root=(200, b"<html>hello</html>")) as s:
            self.assertEqual(check.diagnose_inventree(s.url).code, "not_inventree")

    def test_other_json(self):
        with Server(api_root=(200, {"hello": "world"})) as s:
            self.assertEqual(check.diagnose_inventree(s.url).code, "not_inventree")

    def test_json_list(self):
        with Server(api_root=(200, [1, 2])) as s:
            self.assertEqual(check.diagnose_inventree(s.url).code, "not_inventree")

    def test_too_old(self):
        with Server(api_root=(200, {"server": "InvenTree", "apiVersion": 1})) as s:
            self.assertEqual(check.diagnose_inventree(s.url, "admin", "secret").code, "too_old")

    def test_no_credentials(self):
        with Server() as s:
            self.assertEqual(check.diagnose_inventree(s.url).code, "no_credentials")
            self.assertEqual(check.diagnose_inventree(s.url, username="admin").code, "no_credentials")

    def test_bad_password(self):
        with Server() as s:
            self.assertEqual(check.diagnose_inventree(s.url, "admin", "wrong").code, "auth_failed")

    def test_bad_token(self):
        with Server() as s:
            self.assertEqual(check.diagnose_inventree(s.url, token="nope").code, "auth_failed")

    def test_ok_password(self):
        with Server() as s:
            self.assertTrue(check.diagnose_inventree(s.url, "admin", "secret").ok)

    def test_ok_token(self):
        with Server() as s:
            self.assertTrue(check.diagnose_inventree(s.url, token="tok").ok)

    def test_trailing_api_in_url(self):
        with Server() as s:
            self.assertTrue(check.diagnose_inventree(s.url + "/api/", "admin", "secret").ok)

    def test_error_carries_message(self):
        d = check.diagnose_inventree("")
        err = check.InventreeSetupError(d)
        self.assertIn("Repository preferences", str(err))
        self.assertIs(err.diagnosis, d)


if __name__ == "__main__":
    unittest.main()
