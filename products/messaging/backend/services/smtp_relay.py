"""Setup details and the test send for the SMTP relay. The test connects the way a customer's app does, so a bad
key, a blocked port or an expired certificate shows up here."""

import ssl
import smtplib
from email.message import EmailMessage

from django.conf import settings

from products.messaging.backend.facade.contracts import SmtpTestResult

SMTP_TEST_TEMPLATE_KEY = "smtp-test"
SMTP_TEST_TIMEOUT_SECONDS = 15


def smtp_relay_host() -> str:
    return settings.SMTP_RELAY_HOST


def _message(sender: str, to: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = "PostHog SMTP test"
    message["X-PostHog-Template-Key"] = SMTP_TEST_TEMPLATE_KEY
    message.set_content("This test email was sent through the PostHog SMTP relay.")
    return message


def _reply_text(code: int, text: bytes | str) -> str:
    return f"{code} {text.decode(errors='replace') if isinstance(text, bytes) else text}"


def send_smtp_test(*, password: str, sender: str, to: str) -> SmtpTestResult:
    try:
        with smtplib.SMTP(
            settings.SMTP_RELAY_HOST, settings.SMTP_RELAY_CONNECT_PORT, timeout=SMTP_TEST_TIMEOUT_SECONDS
        ) as client:
            client.starttls(context=ssl.create_default_context())
            client.login("posthog", password)
            client.send_message(_message(sender, to))
            return SmtpTestResult(ok=True, reply="The relay queued the test email.")
    except smtplib.SMTPRecipientsRefused as e:
        code, reply = next(iter(e.recipients.values()))
        return SmtpTestResult(ok=False, reply=_reply_text(code, reply))
    except smtplib.SMTPResponseException as e:
        return SmtpTestResult(ok=False, reply=_reply_text(e.smtp_code, e.smtp_error))
    except (smtplib.SMTPException, OSError):
        return SmtpTestResult(
            ok=False,
            reply="PostHog couldn't reach the SMTP relay. Try again shortly, and contact support if it continues.",
        )
