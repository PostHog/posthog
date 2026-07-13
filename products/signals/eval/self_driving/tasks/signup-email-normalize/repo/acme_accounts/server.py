"""Minimal stdlib HTTP front for the account service."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from acme_accounts.accounts import AccountService, EmailTakenError

service = AccountService()


class AccountsHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        body = self._read_body()
        email = body.get("email", "")
        if self.path == "/api/signup":
            try:
                user = service.create_user(email, body.get("password", ""))
            except EmailTakenError:
                self._send(409, {"error": "email_taken"})
                return
            self._send(201, {"user": user})
        elif self.path == "/api/login":
            user = service.authenticate(email, body.get("password", ""))
            if user is None:
                self._send(401, {"error": "invalid_credentials"})
                return
            self._send(200, {"user": user})
        elif self.path == "/api/password-reset":
            token = service.request_password_reset(email)
            if token is None:
                self._send(404, {"error": "account_not_found"})
                return
            self._send(200, {"reset_token": token})
        else:
            self._send(404, {"error": "not_found"})


def main() -> None:
    server = HTTPServer(("0.0.0.0", 8000), AccountsHandler)
    print("acme-accounts listening on :8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
