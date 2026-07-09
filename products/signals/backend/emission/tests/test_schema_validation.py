import json
import dataclasses
from pathlib import Path

import pytest

from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP
from products.signals.backend.emission.conversations_tickets import conversations_ticket_emitter
from products.signals.backend.emission.github_issues import github_issue_emitter
from products.signals.backend.emission.linear_issues import linear_issue_emitter
from products.signals.backend.emission.pganalyze_issues import pganalyze_issue_emitter
from products.signals.backend.emission.zendesk_tickets import zendesk_ticket_emitter

FIXTURES_DIR = Path(__file__).resolve().parents[5] / "products" / "signals" / "eval" / "fixtures"


def _load_fixture(filename: str) -> list[dict]:
    with open(FIXTURES_DIR / filename) as f:
        return json.load(f)


def _validate_output(output):
    data = dataclasses.asdict(output)
    variant_type = SIGNAL_VARIANT_LOOKUP.get((output.source_product, output.source_type))
    if variant_type is None:
        raise ValueError(f"No SignalInput variant for ({output.source_product}, {output.source_type})")
    variant_type.model_validate(data)


GITHUB_RECORDS = _load_fixture("github_issues.json")
ZENDESK_RECORDS = _load_fixture("zendesk_tickets.json")
LINEAR_RECORDS = _load_fixture("linear_issues.json")
CONVERSATIONS_RECORDS = _load_fixture("conversations_tickets.json")
PGANALYZE_RECORDS = _load_fixture("pganalyze_issues.json")


class TestGithubFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        GITHUB_RECORDS,
        ids=[r.get("html_url", r["id"]) for r in GITHUB_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = github_issue_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)


class TestZendeskFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        ZENDESK_RECORDS,
        ids=[r["id"] for r in ZENDESK_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = zendesk_ticket_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)


class TestLinearFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        LINEAR_RECORDS,
        ids=[r.get("identifier", r["id"]) for r in LINEAR_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = linear_issue_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)


class TestPgAnalyzeFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        PGANALYZE_RECORDS,
        ids=[r["id"] for r in PGANALYZE_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = pganalyze_issue_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)


class TestConversationsFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        CONVERSATIONS_RECORDS,
        ids=[r["id"] for r in CONVERSATIONS_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = conversations_ticket_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)
