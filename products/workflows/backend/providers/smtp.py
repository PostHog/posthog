import ssl
import socket
import logging
import smtplib
import ipaddress

from django.conf import settings

from rest_framework import exceptions

logger = logging.getLogger(__name__)

# Only submission ports. Port 25 stays blocked: unauthenticated relay from cloud IPs is an
# abuse vector and most cloud providers block outbound 25 anyway.
ALLOWED_SMTP_PORTS = {587, 465, 2525}

SMTP_ENCRYPTION_MODES = {"starttls", "ssl", "none"}

SMTP_CONNECTION_TIMEOUT_SECONDS = 10


class SMTPProvider:
    """Custom SMTP relay provider for workflow email sends.

    Unlike SESProvider there is no remote state to manage (no tenants, identities, or DNS
    records) — the customer's relay already handles DKIM/SPF for their domain. The provider's
    job is credential/connection verification; actual delivery happens in the Node email
    worker using the same integration config.
    """

    def test_connection(
        self,
        host: str,
        port: int,
        encryption: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Connect, negotiate TLS, and authenticate against the relay. Raises ValidationError
        with a user-facing message on the first failure; returns None on success."""
        self._validate_settings(host, port, encryption, username, password)
        self._raise_if_host_unsafe(host)

        smtp: smtplib.SMTP | None = None
        try:
            if encryption == "ssl":
                smtp = smtplib.SMTP_SSL(
                    host, port, timeout=SMTP_CONNECTION_TIMEOUT_SECONDS, context=ssl.create_default_context()
                )
            else:
                smtp = smtplib.SMTP(host, port, timeout=SMTP_CONNECTION_TIMEOUT_SECONDS)

            # The pre-connect resolution check above is subject to DNS rebinding; re-checking the
            # peer of the socket we actually opened closes that window (same pattern as
            # posthog.api.utils.raise_if_connected_to_private_ip).
            self._raise_if_peer_private(smtp)

            if encryption == "starttls":
                smtp.starttls(context=ssl.create_default_context())

            if username and password:
                smtp.login(username, password)
        except exceptions.ValidationError:
            raise
        except smtplib.SMTPAuthenticationError as e:
            raise exceptions.ValidationError(
                f"The SMTP server rejected the credentials ({e.smtp_code}): {e.smtp_error.decode(errors='replace') if isinstance(e.smtp_error, bytes) else e.smtp_error}"
            )
        except smtplib.SMTPNotSupportedError:
            raise exceptions.ValidationError(
                "The SMTP server does not support the requested feature (STARTTLS or AUTH). Check the encryption mode and port."
            )
        except ssl.SSLError as e:
            raise exceptions.ValidationError(
                f"TLS negotiation with the SMTP server failed: {e.reason or e}. Check the encryption mode matches the port (SSL is usually 465, STARTTLS is usually 587)."
            )
        except TimeoutError:
            raise exceptions.ValidationError(
                f"Timed out connecting to {host}:{port}. Check the host and port, and that your provider allows connections from PostHog."
            )
        except ConnectionRefusedError:
            raise exceptions.ValidationError(f"Connection to {host}:{port} was refused. Check the host and port.")
        except socket.gaierror:
            raise exceptions.ValidationError(f"Could not resolve SMTP host {host}. Check the hostname.")
        except (OSError, smtplib.SMTPException) as e:
            logger.warning("SMTP connection test failed", extra={"host": host, "port": port, "error": str(e)})
            raise exceptions.ValidationError(f"Could not connect to the SMTP server: {e}")
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except (OSError, smtplib.SMTPException):
                    pass

    def _validate_settings(
        self, host: str, port: int, encryption: str, username: str | None, password: str | None
    ) -> None:
        if not host:
            raise exceptions.ValidationError("SMTP host is required")
        if port not in ALLOWED_SMTP_PORTS:
            raise exceptions.ValidationError(
                f"SMTP port must be one of {sorted(ALLOWED_SMTP_PORTS)}. Port 25 is not supported."
            )
        if encryption not in SMTP_ENCRYPTION_MODES:
            raise exceptions.ValidationError("SMTP encryption must be one of 'starttls', 'ssl' or 'none'")
        if encryption == "none" and not settings.DEBUG:
            raise exceptions.ValidationError("Unencrypted SMTP connections are not supported")
        if bool(username) != bool(password):
            raise exceptions.ValidationError("SMTP username and password must be provided together")
        if not username and not settings.DEBUG:
            raise exceptions.ValidationError("SMTP credentials are required")

    def _raise_if_host_unsafe(self, host: str) -> None:
        if settings.DEBUG:
            # Local dev points at maildev/mailpit on localhost
            return
        try:
            addrinfo = socket.getaddrinfo(host, None)
        except socket.gaierror:
            raise exceptions.ValidationError(f"Could not resolve SMTP host {host}. Check the hostname.")
        for _, _, _, _, sockaddr in addrinfo:
            if not ipaddress.ip_address(sockaddr[0]).is_global:
                raise exceptions.ValidationError("SMTP host resolves to a private or reserved address")

    def _raise_if_peer_private(self, smtp: smtplib.SMTP) -> None:
        if settings.DEBUG:
            return
        sock = getattr(smtp, "sock", None)
        if sock is None:
            raise exceptions.ValidationError("Could not verify the SMTP connection")
        if not ipaddress.ip_address(sock.getpeername()[0]).is_global:
            raise exceptions.ValidationError("SMTP host resolves to a private or reserved address")
