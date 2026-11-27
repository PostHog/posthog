"""Flag warehouse columns that likely hold personal or secret data, from the column name and type.

No values are read. A flag is a suggestion to mask the column, so a missed column is worse than an
extra one, but a flag on every `name` or `status` column would teach people to ignore the flags.
"""

import re
from collections.abc import Sequence

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import WarehouseColumnSensitivity

_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

# Words that turn a column into a fact about the data rather than the data: `email_verified`, `token_type`.
_METADATA_WORDS = frozenset(
    {
        "bounced",
        "consent",
        "count",
        "country",
        "domain",
        "enabled",
        "format",
        "has",
        "is",
        "length",
        "opt",
        "optin",
        "optout",
        "provider",
        "region",
        "status",
        "subscribed",
        "template",
        "type",
        "valid",
        "validated",
        "verified",
    }
)

# An identifier of the thing, not the thing, but only at the end: `email_id` is a key, `id_token` is a secret.
_TRAILING_METADATA_WORDS = frozenset({"id", "ids", "uuid"})


@frozen
class _Rule:
    sensitivity: WarehouseColumnSensitivity
    phrases: frozenset[str]
    excluded_words: frozenset[str] = frozenset()
    # Glued names such as `useremail` match when a word ends with one of these.
    word_suffixes: frozenset[str] = frozenset()
    # Only the end of the name counts, so `email_subject` and `ip_city` describe something else.
    trailing_only: bool = False
    allows_number: bool = False
    allows_temporal: bool = False


# Checked in order, so `email_address` is an email and `ip_address` an IP, not a street address.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        sensitivity=WarehouseColumnSensitivity.EMAIL,
        phrases=frozenset({"email", "emails", "emailaddress", "mail"}),
        word_suffixes=frozenset({"email"}),
        trailing_only=True,
    ),
    _Rule(
        sensitivity=WarehouseColumnSensitivity.IP_ADDRESS,
        phrases=frozenset(
            {"ip", "ipaddress", "ipaddr", "ipv4", "ipv6", "ipv4address", "ipv6address", "remoteaddr", "remoteaddress"}
        ),
        trailing_only=True,
        allows_number=True,
    ),
    _Rule(
        sensitivity=WarehouseColumnSensitivity.CARD_NUMBER,
        phrases=frozenset({"cardnumber", "cardno", "cardnum", "creditcard", "ccnumber", "pan", "cvv", "cvc"}),
        # A card's brand, last four digits and expiry are safe to keep in plaintext.
        excluded_words=frozenset({"brand", "check", "exp", "expiry", "expiration", "fingerprint", "funding", "last"}),
        allows_number=True,
    ),
    _Rule(
        sensitivity=WarehouseColumnSensitivity.DATE_OF_BIRTH,
        phrases=frozenset({"dob", "dateofbirth", "birthdate", "birthday", "birth", "bday"}),
        allows_number=True,
        allows_temporal=True,
    ),
    _Rule(
        sensitivity=WarehouseColumnSensitivity.PHONE,
        phrases=frozenset({"phone", "phonenumber", "mobilenumber", "cellphone", "telephone", "msisdn", "fax"}),
        excluded_words=frozenset(
            {"earphone", "earphones", "headphone", "headphones", "iphone", "microphone", "smartphone"}
        ),
        word_suffixes=frozenset({"phone"}),
        allows_number=True,
    ),
    # `mobile` alone is a number only at the end: `mobile_os` and `mobile_sessions` describe devices.
    _Rule(
        sensitivity=WarehouseColumnSensitivity.PHONE,
        phrases=frozenset({"mobile"}),
        excluded_words=frozenset({"app", "device", "os", "platform"}),
        trailing_only=True,
        allows_number=True,
    ),
    _Rule(
        sensitivity=WarehouseColumnSensitivity.TOKEN,
        phrases=frozenset({"token", "tokens", "apikey", "authkey", "sessionkey", "bearer", "jwt"}),
        excluded_words=frozenset({"expires", "expiry", "limit", "name", "scope", "scopes", "usage", "used"}),
    ),
    _Rule(
        sensitivity=WarehouseColumnSensitivity.SECRET,
        phrases=frozenset(
            {"secret", "secrets", "password", "passwd", "pwd", "passphrase", "privatekey", "secretkey", "signingkey"}
        ),
        excluded_words=frozenset({"policy", "required", "strength"}),
    ),
    _Rule(
        sensitivity=WarehouseColumnSensitivity.ADDRESS,
        phrases=frozenset(
            {
                "address",
                "addresses",
                "addressline",
                "street",
                "streetaddress",
                "streetname",
                "postcode",
                "postalcode",
                "zip",
                "zipcode",
            }
        ),
        excluded_words=frozenset({"check", "contract", "mac", "wallet"}),
        word_suffixes=frozenset({"address"}),
        trailing_only=True,
        allows_number=True,
    ),
    # A bare `name` is usually a product or a company, so only person-name phrases count.
    _Rule(
        sensitivity=WarehouseColumnSensitivity.NAME,
        phrases=frozenset(
            {
                "firstname",
                "lastname",
                "fullname",
                "givenname",
                "familyname",
                "middlename",
                "maidenname",
                "surname",
                "nickname",
                "displayname",
                "legalname",
                "username",
                "fname",
                "lname",
                "contactname",
                "customername",
                "holdername",
                "cardholdername",
                "recipientname",
                "billingname",
                "shippingname",
            }
        ),
        excluded_words=frozenset(
            {
                "app",
                "campaign",
                "channel",
                "company",
                "event",
                "file",
                "group",
                "org",
                "organization",
                "pipeline",
                "plan",
                "product",
                "stage",
                "team",
                "template",
            }
        ),
    ),
)


def _words(column_name: str) -> list[str]:
    return [word.lower() for word in _WORD.findall(column_name)]


def _phrases(words: Sequence[str]) -> set[str]:
    # Joins up to three neighboring words, so `first_name`, `firstName` and `firstname` all read as `firstname`.
    return {"".join(words[start : start + size]) for size in (1, 2, 3) for start in range(len(words) - size + 1)}


def _type_kind(data_type: str | None) -> str | None:
    lowered = (data_type or "").lower()
    if "bool" in lowered:
        return "boolean"
    if any(marker in lowered for marker in ("date", "time", "interval")):
        return "temporal"
    if any(marker in lowered for marker in ("float", "double", "real")):
        return "float"
    if any(marker in lowered for marker in ("int", "serial", "decimal", "numeric", "number")):
        return "number"
    return None


def classify_column_sensitivity(column_name: str, data_type: str | None = None) -> WarehouseColumnSensitivity | None:
    """The kind of sensitive data the column likely holds, or None. `data_type` may be any source's type name."""
    words = _words(column_name)
    if not words or _METADATA_WORDS.intersection(words) or words[-1] in _TRAILING_METADATA_WORDS:
        return None
    kind = _type_kind(data_type)
    if kind in ("boolean", "float"):
        return None
    phrases = _phrases(words)
    # Trailing digits are a numbering, not a new meaning: `address_line_2` still ends in an address.
    core = list(words)
    while len(core) > 1 and core[-1].isdigit():
        core.pop()
    trailing_phrases = {"".join(end[-size:]) for end in (core, words) for size in (1, 2, 3) if size <= len(end)}
    for rule in _RULES:
        if kind == "number" and not rule.allows_number:
            continue
        if kind == "temporal" and not rule.allows_temporal:
            continue
        if rule.excluded_words.intersection(words):
            continue
        candidates = trailing_phrases if rule.trailing_only else phrases
        suffix_words = core[-1:] if rule.trailing_only else words
        if rule.phrases.intersection(candidates) or any(
            word.endswith(suffix) for word in suffix_words for suffix in rule.word_suffixes
        ):
            return rule.sensitivity
    return None
