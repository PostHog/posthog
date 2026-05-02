"""
Customer-facing copy and translations for proxy diagnostic messages.

All user-visible strings live here so copy can be reviewed in one place. Functions
return PostHog-flavored sentences without leaking vendor terminology (no mentions of
Cloudflare, pki.goog, pending_validation, etc.) into the customer surface.
"""

from typing import Final

# Cloudflare's `ssl.certificate_authority` field → CAA-record issuer string.
# Used by the CAA tree-walk check to determine which issuer must be authorized.
CA_TO_CAA_ISSUER: Final[dict[str, str]] = {
    "google": "pki.goog",
    "lets_encrypt": "letsencrypt.org",
    "ssl_com": "ssl.com",
    "digicert": "digicert.com",
}

# Issuers we want a customer to whitelist when they need to fix CAA records. Listing
# all three keeps them covered if Cloudflare rotates which CA actually issues their cert.
DEFAULT_ALLOWED_CAA_ISSUERS: Final[tuple[str, ...]] = (
    "pki.goog",
    "letsencrypt.org",
    "ssl.com",
)


def caa_blocking(domain: str, restricting_zone: str, allowed: list[str], required_issuer: str) -> str:
    allowed_str = ", ".join(f"`{i}`" for i in allowed) if allowed else "no issuers"
    return (
        f"Your DNS provider's CAA records on `{restricting_zone}` allow only {allowed_str}, "
        f"which prevents our certificate authority from issuing a certificate for `{domain}`. "
        f"Add a CAA record authorizing `{required_issuer}` to your DNS to unblock issuance."
    )


def cname_missing(domain: str) -> str:
    return f"`{domain}` doesn't have a CNAME DNS record yet. Add the record below at your DNS provider."


def cname_mismatch(domain: str, actual: str) -> str:
    return (
        f"`{domain}` is pointing to `{actual}` instead of the expected target. "
        "Update the CNAME record below at your DNS provider."
    )


def http_challenge_unreachable(domain: str) -> str:
    return (
        f"We can't reach the verification challenge URL on `{domain}`. "
        "Confirm your domain is publicly accessible on port 80 with no redirects to HTTPS, "
        "no firewall blocking, and no other CDN in front."
    )


def http_challenge_wrong_body(domain: str) -> str:
    return (
        f"The verification challenge URL on `{domain}` returned the wrong content. "
        "This usually means another CDN or proxy is intercepting traffic before it reaches us. "
        "Check whether you have a different reverse proxy configured for this domain."
    )


def cloudflare_hostname_missing(domain: str) -> str:
    return f"We don't have a record of this proxy on our side for `{domain}`. Hit Retry to recreate it."


def pending_issuance(domain: str) -> str:
    return (
        f"Verification succeeded for `{domain}` but the certificate hasn't been issued yet. "
        "Wait up to an hour. Hit Retry if it stays this way."
    )


def cert_expiring_soon(domain: str, days_remaining: int) -> str:
    return (
        f"The TLS certificate for `{domain}` expires in {days_remaining} days and isn't being renewed. "
        "Hit Retry to start a fresh issuance."
    )
