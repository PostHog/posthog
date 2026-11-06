"""Binds REQUIRED_TABLES to the package's SQL; drift otherwise first fails in production."""

import re
from pathlib import Path

from llm_gateway.db.required_tables import REQUIRED_TABLES

SRC_ROOT = Path(__file__).parent.parent / "src" / "llm_gateway"

# DELETE FROM is covered by FROM.
TABLE_REF = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+((?:posthog_|ee_)[a-z0-9_]+)", re.IGNORECASE)


def referenced_tables() -> set[str]:
    tables: set[str] = set()
    for path in SRC_ROOT.rglob("*.py"):
        tables.update(match.lower() for match in TABLE_REF.findall(path.read_text(encoding="utf-8")))
    return tables


def test_sql_table_references_match_declaration() -> None:
    referenced = referenced_tables()
    assert referenced, "table extraction found no SQL references; the regex or source layout changed"

    undeclared = referenced - REQUIRED_TABLES
    stale = REQUIRED_TABLES - referenced
    assert not undeclared, (
        f"SQL references tables missing from REQUIRED_TABLES: {sorted(undeclared)}. "
        "The gateway role cannot read a table without a SELECT grant in "
        "posthog-cloud-infra (terraform/environments/<env>/**/users.tf). "
        "Land the grant in every environment first, then declare the table in "
        "llm_gateway/db/required_tables.py."
    )
    assert not stale, (
        f"REQUIRED_TABLES declares tables no SQL references: {sorted(stale)}. "
        "Remove them from llm_gateway/db/required_tables.py so the declaration "
        "stays trustworthy (revoking the grant in posthog-cloud-infra is optional)."
    )
