"""Flag warehouse columns that likely hold personal or secret data, from the column name and type.

No values are read. A flag is a suggestion to mask the column, so a missed column is worse than an
extra one, but a flag on every `name` or `status` column would teach people to ignore the flags.
"""

import re
from collections.abc import Sequence

from django.utils import timezone

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.types import WarehouseColumnSensitivity

Sensitivity = WarehouseColumnSensitivity

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
        "id",
        "ids",
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
        "uuid",
        "valid",
        "validated",
        "verified",
    }
)

_MAX_COLUMN_NAME_LENGTH: int = WarehouseColumnAnnotation._meta.get_field("column_name").max_length or 400


@frozen
class _Rule:
    sensitivity: WarehouseColumnSensitivity
    phrases: frozenset[str]
    excluded_words: frozenset[str] = frozenset()
    allows_number: bool = False
    allows_temporal: bool = False


# Checked in order, so `email_address` is an email and `ip_address` an IP, not a street address.
_RULES: tuple[_Rule, ...] = (
    _Rule(sensitivity=Sensitivity.EMAIL, phrases=frozenset({"email", "emails", "emailaddress", "mail"})),
    _Rule(
        sensitivity=Sensitivity.IP_ADDRESS,
        phrases=frozenset({"ip", "ipaddress", "ipaddr", "ipv4", "ipv6", "remoteaddr", "remoteaddress"}),
        allows_number=True,
    ),
    _Rule(
        sensitivity=Sensitivity.CARD_NUMBER,
        phrases=frozenset({"cardnumber", "cardno", "cardnum", "creditcard", "ccnumber", "pan", "cvv", "cvc"}),
        # A card's brand, last four digits and expiry are safe to keep in plaintext.
        excluded_words=frozenset({"brand", "exp", "expiry", "expiration", "fingerprint", "funding", "last"}),
        allows_number=True,
    ),
    _Rule(
        sensitivity=Sensitivity.DATE_OF_BIRTH,
        phrases=frozenset({"dob", "dateofbirth", "birthdate", "birthday", "birth", "bday"}),
        allows_number=True,
        allows_temporal=True,
    ),
    _Rule(
        sensitivity=Sensitivity.PHONE,
        phrases=frozenset(
            {"phone", "phonenumber", "mobilenumber", "mobilephone", "cellphone", "telephone", "msisdn", "fax"}
        ),
        allows_number=True,
    ),
    _Rule(
        sensitivity=Sensitivity.TOKEN,
        phrases=frozenset({"token", "tokens", "apikey", "authkey", "sessionkey", "bearer", "jwt"}),
        excluded_words=frozenset({"expires", "expiry", "limit", "name", "scope", "scopes", "usage", "used"}),
    ),
    _Rule(
        sensitivity=Sensitivity.SECRET,
        phrases=frozenset(
            {"secret", "secrets", "password", "passwd", "pwd", "passphrase", "privatekey", "secretkey", "signingkey"}
        ),
        excluded_words=frozenset({"policy", "required", "strength"}),
    ),
    _Rule(
        sensitivity=Sensitivity.ADDRESS,
        phrases=frozenset(
            {
                "address",
                "addresses",
                "addressline",
                "street",
                "streetaddress",
                "postcode",
                "postalcode",
                "zip",
                "zipcode",
            }
        ),
        excluded_words=frozenset({"contract", "mac", "wallet"}),
    ),
    # A bare `name` is usually a product or a company, so only person-name phrases count.
    _Rule(
        sensitivity=Sensitivity.NAME,
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
                "recipientname",
                "billingname",
                "shippingname",
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
    if not words or _METADATA_WORDS.intersection(words):
        return None
    kind = _type_kind(data_type)
    if kind in ("boolean", "float"):
        return None
    phrases = _phrases(words)
    for rule in _RULES:
        if kind == "number" and not rule.allows_number:
            continue
        if kind == "temporal" and not rule.allows_temporal:
            continue
        if rule.excluded_words.intersection(words):
            continue
        if rule.phrases.intersection(phrases):
            return rule.sensitivity
    return None


def _expected_sensitivities(table: DataWarehouseTable) -> dict[str, WarehouseColumnSensitivity | None]:
    return {
        column["name"]: classify_column_sensitivity(column["name"], column.get("data_type"))
        for column in table.get_user_facing_columns()
        if column.get("name") and len(column["name"]) <= _MAX_COLUMN_NAME_LENGTH
    }


def column_sensitivity_pending(team_id: int, table: DataWarehouseTable) -> bool:
    """Whether any stored sensitivity differs from what the columns classify as now."""
    stored = dict(
        WarehouseColumnAnnotation.objects.for_team(team_id)
        .filter(table_id=table.id)
        .values_list("column_name", "sensitivity")
    )
    return any(stored.get(name) != sensitivity for name, sensitivity in _expected_sensitivities(table).items())


def classify_table_columns(team_id: int, table: DataWarehouseTable) -> int:
    """Store each column's sensitivity on its annotation and return how many rows changed.

    A flagged column without an annotation gets a row with an empty description, which the
    description pass fills in later.
    """
    expected = _expected_sensitivities(table)
    stored = {
        annotation.column_name: annotation
        for annotation in WarehouseColumnAnnotation.objects.for_team(team_id)
        .filter(table_id=table.id)
        .only("id", "column_name", "sensitivity")
    }
    now = timezone.now()
    created: list[WarehouseColumnAnnotation] = []
    changed: list[WarehouseColumnAnnotation] = []
    for name, sensitivity in expected.items():
        annotation = stored.get(name)
        if annotation is None:
            if sensitivity is not None:
                created.append(
                    WarehouseColumnAnnotation(
                        team_id=team_id, table=table, column_name=name, description="", sensitivity=sensitivity
                    )
                )
        elif annotation.sensitivity != sensitivity:
            annotation.sensitivity = sensitivity
            annotation.updated_at = now
            changed.append(annotation)
    # A description written since the read above already made the row, so a conflict leaves that row unflagged
    # until the next pass.
    WarehouseColumnAnnotation.objects.for_team(team_id).bulk_create(created, ignore_conflicts=True)
    WarehouseColumnAnnotation.objects.for_team(team_id).bulk_update(changed, ["sensitivity", "updated_at"])
    return len(created) + len(changed)
