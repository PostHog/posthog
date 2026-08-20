import hmac
import base64
import hashlib

from django.conf import settings

# Postmark's SMTP relay endpoint, prefilled in the setup UI
POSTMARK_SMTP_HOST = "smtp.postmarkapp.com"


def email_webhook_token(integration_id: int | str) -> str:
    # Must stay byte-identical with the Node implementation (EmailTrackingCodeSigner.webhookToken):
    # HMAC-SHA256 over "webhook:<id>" with the first ENCRYPTION_SALT_KEYS key, truncated to
    # 16 bytes, base64url without padding. The Node CDP API verifies what Django displays here.
    key = settings.ENCRYPTION_SALT_KEYS[0]
    mac = hmac.new(key.encode(), f"webhook:{integration_id}".encode(), hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def postmark_webhook_url(integration_id: int | str) -> str:
    base = (settings.EMAIL_TRACKING_URL or settings.SITE_URL).rstrip("/")
    return f"{base}/public/m/postmark_webhook/{integration_id}?token={email_webhook_token(integration_id)}"
