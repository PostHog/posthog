import base64
import socket
import threading
from typing import Any

from unittest import TestCase

from django.test import override_settings

from parameterized import parameterized
from rest_framework import exceptions

from products.workflows.backend.providers.smtp import SMTPProvider

# In the allowlist, unprivileged, and not used by other local test services (maildev is 1025).
TEST_SMTP_PORT = 2525


class FakeSMTPServer(threading.Thread):
    """A minimal in-process SMTP server speaking the real protocol over a real socket,
    so SMTPProvider is exercised through actual smtplib I/O without any external network."""

    def __init__(
        self,
        advertise_starttls: bool = False,
        starttls_garbage: bool = False,
        accept_user: str | None = None,
        accept_password: str | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.advertise_starttls = advertise_starttls
        self.starttls_garbage = starttls_garbage
        self.accept_user = accept_user
        self.accept_password = accept_password
        self.received_credentials: tuple[str, str] | None = None
        self.saw_ehlo = False
        self._stop_event = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", TEST_SMTP_PORT))
        self.sock.listen(5)
        self.sock.settimeout(0.2)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5)
        self.sock.close()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            try:
                self._serve_connection(conn)
            except OSError:
                pass
            finally:
                conn.close()

    def _serve_connection(self, conn: socket.socket) -> None:
        conn.settimeout(5)
        conn.sendall(b"220 test.local ESMTP fake\r\n")
        buffer = b""
        while True:
            data = conn.recv(1024)
            if not data:
                return
            buffer += data
            while b"\r\n" in buffer:
                line, buffer = buffer.split(b"\r\n", 1)
                if not self._respond(conn, line.decode(errors="replace")):
                    return

    def _respond(self, conn: socket.socket, line: str) -> bool:
        command = line.split(" ")[0].upper()
        if command in ("EHLO", "HELO"):
            self.saw_ehlo = True
            extensions = ["250-test.local", "250-AUTH PLAIN"]
            if self.advertise_starttls:
                extensions.append("250-STARTTLS")
            extensions.append("250 SIZE 10485760")
            conn.sendall(("\r\n".join(extensions) + "\r\n").encode())
        elif command == "AUTH":
            payload = base64.b64decode(line.split(" ")[2])
            _, user, password = payload.decode().split("\x00")
            self.received_credentials = (user, password)
            if user == self.accept_user and password == self.accept_password:
                conn.sendall(b"235 2.7.0 Authentication successful\r\n")
            else:
                conn.sendall(b"535 5.7.8 Authentication credentials invalid\r\n")
        elif command == "STARTTLS":
            conn.sendall(b"220 2.0.0 Ready to start TLS\r\n")
            if self.starttls_garbage:
                # The client now expects a TLS ServerHello; plain text forces an SSLError,
                # exercising the TLS-failure classification without needing certificates.
                conn.sendall(b"THIS IS NOT TLS\r\n" * 4)
                return False
        elif command == "QUIT":
            conn.sendall(b"221 2.0.0 Bye\r\n")
            return False
        else:
            conn.sendall(b"250 2.0.0 OK\r\n")
        return True


VALID_SMTP_KWARGS: dict[str, Any] = {
    "host": "smtp.example.com",
    "port": 587,
    "encryption": "starttls",
    "username": "apikey",
    "password": "secret",
}


class TestSMTPProviderValidation(TestCase):
    @parameterized.expand(
        [
            ("port_25_blocked", {"port": 25}, "must be one of"),
            ("arbitrary_port_blocked", {"port": 8025}, "must be one of"),
            ("unknown_encryption", {"encryption": "tls"}, "must be one of 'starttls', 'ssl' or 'none'"),
            ("username_without_password", {"password": None}, "must be provided together"),
            ("password_without_username", {"username": None}, "must be provided together"),
            ("missing_host", {"host": ""}, "host is required"),
        ]
    )
    def test_rejects_invalid_settings(self, _name: str, overrides: dict, expected_error: str) -> None:
        with override_settings(DEBUG=True):
            with self.assertRaises(exceptions.ValidationError) as ctx:
                SMTPProvider().test_connection(**{**VALID_SMTP_KWARGS, **overrides})
        assert expected_error in str(ctx.exception)

    @parameterized.expand(
        [
            ("unencrypted_blocked_in_prod", {"encryption": "none"}, "not supported"),
            ("credentials_required_in_prod", {"username": None, "password": None}, "credentials are required"),
        ]
    )
    def test_production_only_guards(self, _name: str, overrides: dict, expected_error: str) -> None:
        with override_settings(DEBUG=False):
            with self.assertRaises(exceptions.ValidationError) as ctx:
                SMTPProvider().test_connection(**{**VALID_SMTP_KWARGS, **overrides})
        assert expected_error in str(ctx.exception)

    @parameterized.expand(
        [
            ("loopback_hostname", "localhost"),
            ("loopback_literal", "127.0.0.1"),
            ("cloud_metadata", "169.254.169.254"),
            ("private_range", "10.0.0.1"),
        ]
    )
    def test_rejects_private_hosts_outside_debug(self, _name: str, host: str) -> None:
        with override_settings(DEBUG=False):
            with self.assertRaises(exceptions.ValidationError) as ctx:
                SMTPProvider().test_connection(**{**VALID_SMTP_KWARGS, "host": host})
        assert "private or reserved address" in str(ctx.exception)


class TestSMTPProviderRealConnection(TestCase):
    server: FakeSMTPServer | None = None

    def tearDown(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None

    def _start_server(self, **kwargs) -> FakeSMTPServer:
        self.server = FakeSMTPServer(**kwargs)
        self.server.start()
        return self.server

    def test_connects_and_authenticates(self) -> None:
        server = self._start_server(accept_user="apikey", accept_password="secret")
        with override_settings(DEBUG=True):
            SMTPProvider().test_connection(
                host="127.0.0.1", port=TEST_SMTP_PORT, encryption="none", username="apikey", password="secret"
            )
        assert server.saw_ehlo
        assert server.received_credentials == ("apikey", "secret")

    def test_rejected_credentials_surface_the_server_response(self) -> None:
        self._start_server(accept_user="apikey", accept_password="secret")
        with override_settings(DEBUG=True):
            with self.assertRaises(exceptions.ValidationError) as ctx:
                SMTPProvider().test_connection(
                    host="127.0.0.1", port=TEST_SMTP_PORT, encryption="none", username="apikey", password="wrong"
                )
        assert "rejected the credentials (535)" in str(ctx.exception)

    def test_starttls_unsupported_by_server(self) -> None:
        self._start_server(advertise_starttls=False)
        with override_settings(DEBUG=True):
            with self.assertRaises(exceptions.ValidationError) as ctx:
                SMTPProvider().test_connection(
                    host="127.0.0.1", port=TEST_SMTP_PORT, encryption="starttls", username="apikey", password="secret"
                )
        assert "does not support the requested feature" in str(ctx.exception)

    def test_failed_tls_handshake_is_reported_as_tls_error(self) -> None:
        self._start_server(advertise_starttls=True, starttls_garbage=True)
        with override_settings(DEBUG=True):
            with self.assertRaises(exceptions.ValidationError) as ctx:
                SMTPProvider().test_connection(
                    host="127.0.0.1", port=TEST_SMTP_PORT, encryption="starttls", username="apikey", password="secret"
                )
        assert "TLS negotiation with the SMTP server failed" in str(ctx.exception)

    def test_connection_refused(self) -> None:
        # Bind and immediately close so the port is guaranteed free and refusing.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", TEST_SMTP_PORT))
        probe.close()
        with override_settings(DEBUG=True):
            with self.assertRaises(exceptions.ValidationError) as ctx:
                SMTPProvider().test_connection(
                    host="127.0.0.1", port=TEST_SMTP_PORT, encryption="none", username="apikey", password="secret"
                )
        assert "was refused" in str(ctx.exception)
