from django.db import connection
from django.db.models import F, Func, Value
from django.db.models.functions import Lower

# Every character Python's str.isspace() accepts, which is what DRF strips from request fields. PostgreSQL's BTRIM
# takes the same explicit set, so stored rows and request input are trimmed alike.
_WHITESPACE = "".join(
    chr(code_point)
    for code_point in (
        *range(0x09, 0x0E),
        *range(0x1C, 0x21),
        0x85,
        0xA0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
    )
)


def normalized_identifier() -> Lower:
    """The stored identifier with surrounding whitespace trimmed and lower-cased, as an ORM expression.

    Lower-casing runs in PostgreSQL, like the case-insensitive recipient lookup that email sends make.
    """
    return Lower(Func(F("identifier"), Value(_WHITESPACE), function="BTRIM"))


def normalize(identifier: str) -> str:
    """The identifier as `normalized_identifier` would store it, computed by PostgreSQL with the same rule."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT lower(btrim(%s, %s))", [identifier, _WHITESPACE])
        return cursor.fetchone()[0]
