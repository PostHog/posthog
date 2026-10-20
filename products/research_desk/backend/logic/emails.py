from email.utils import parseaddr


def normalize_email(value: str) -> str:
    """Lowercase an address and drop any display name, as in "Ada <ada@example.com>"."""
    _, address = parseaddr(value)
    return (address or value).strip().lower()


def normalize_emails(values: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({email for email in (normalize_email(v) for v in values) if "@" in email})


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1]


def normalize_domain(value: str) -> str:
    return value.strip().lower().lstrip("@")
