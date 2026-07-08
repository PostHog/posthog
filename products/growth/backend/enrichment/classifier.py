import os
import enum
from functools import lru_cache

from posthog.utils import GenericEmails

_DOMAIN_LISTS_DIR = os.path.dirname(__file__)


class CompanyType(enum.StrEnum):
    PERSONAL_EMAIL = "personal_email"
    YC = "yc"
    ENTERPRISE = "enterprise"
    WORK_EMAIL_OTHER = "work_email_other"
    UNKNOWN = "unknown"


class _DomainList:
    def __init__(self, filename: str) -> None:
        with open(os.path.join(_DOMAIN_LISTS_DIR, filename), encoding="utf-8") as f:
            self.domains = {line for raw in f if (line := raw.strip()) and not line.startswith("#")}

    def __contains__(self, domain: str) -> bool:
        return domain in self.domains


@lru_cache(maxsize=1)
def _yc_domains() -> _DomainList:
    return _DomainList("yc_domains.txt")


@lru_cache(maxsize=1)
def _enterprise_domains() -> _DomainList:
    return _DomainList("enterprise_domains.txt")


@lru_cache(maxsize=1)
def _generic_emails() -> GenericEmails:
    return GenericEmails()


def classify_company_type(email: str) -> CompanyType:
    if not email or "@" not in email:
        return CompanyType.UNKNOWN
    domain = email.rsplit("@", 1)[1].strip().lower()
    if not domain:
        return CompanyType.UNKNOWN
    if domain in _yc_domains():
        return CompanyType.YC
    if domain in _enterprise_domains():
        return CompanyType.ENTERPRISE
    if _generic_emails().is_generic(f"@{domain}"):
        return CompanyType.PERSONAL_EMAIL
    return CompanyType.WORK_EMAIL_OTHER
