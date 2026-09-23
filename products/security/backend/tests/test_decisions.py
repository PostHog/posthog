import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.security.backend.facade.enums import Surface
from products.security.backend.logic.decisions import deciding_rule, is_protected_domain
from products.security.backend.logic.matching import build_index
from products.security.backend.logic.rules import SnapshotRule
from products.security.backend.logic.subjects import normalize_subject

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "access-rules.json").read_text())
ORDER = [Surface.SIGNUP, Surface.APP, Surface.AI_GATEWAY, Surface.EMAIL_CODE]
LETTERS = {Surface.EMAIL_CODE: "E"}


def _cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    return [(f"{suite['name']}: {case['name']}", suite, case) for suite in VECTORS["suites"] for case in suite["cases"]]


def _letter(surface: Surface, rule: SnapshotRule | None) -> str:
    if rule is None:
        return "A"
    return LETTERS.get(surface, "B")


class TestVectors(TestCase):
    @parameterized.expand(_cases())
    def test_vector(self, _name: str, suite: dict[str, Any], case: dict[str, Any]) -> None:
        rules = [SnapshotRule.from_wire(raw) for raw in suite["rules"]]
        index = build_index(rule for rule in rules if rule is not None)
        now = datetime.fromisoformat(suite["now"])
        raw = case["subject"]
        subject = normalize_subject(
            email=raw.get("email"),
            domain=raw.get("domain"),
            user_uuid=raw.get("userUuid"),
            organization_ids=tuple(raw.get("organizationIds", ())),
            ip=raw.get("ip"),
        )
        decided = {surface: deciding_rule(index, subject, surface, now) for surface in ORDER}
        assert "".join(_letter(s, decided[s]) for s in ORDER) == case["expect"]
        for surface, rule_id in case.get("deciding", {}).items():
            rule = decided[Surface(surface)]
            assert rule is not None and rule.id == rule_id


class TestWireParsing(TestCase):
    @parameterized.expand(
        [
            ("not a dict", "rule"),
            ("missing field", {"id": "a", "targetType": "email", "targetValue": "x", "effect": "block"}),
            (
                "non-string field",
                {"id": 1, "targetType": "email", "targetValue": "x", "effect": "block", "scope": "signup"},
            ),
            (
                "bad expiry",
                {
                    "id": "a",
                    "targetType": "email",
                    "targetValue": "x",
                    "effect": "block",
                    "scope": "signup",
                    "expiresAt": "soon",
                },
            ),
            (
                "naive expiry",
                {
                    "id": "a",
                    "targetType": "email",
                    "targetValue": "x",
                    "effect": "block",
                    "scope": "signup",
                    "expiresAt": "2026-09-01T00:00:00",
                },
            ),
            (
                "bad network",
                {"id": "a", "targetType": "ip", "targetValue": "not-a-range", "effect": "block", "scope": "signup"},
            ),
        ]
    )
    def test_malformed_rules_are_skipped(self, _name: str, raw: object) -> None:
        assert SnapshotRule.from_wire(raw) is None

    def test_expiry_is_timezone_aware(self) -> None:
        rule = SnapshotRule.from_wire(
            {
                "id": "a",
                "targetType": "email",
                "targetValue": "x",
                "effect": "block",
                "scope": "signup",
                "expiresAt": "2026-09-01T00:00:00.000Z",
            }
        )
        assert rule is not None and rule.expires_at == datetime(2026, 9, 1, tzinfo=UTC)


class TestProtectedDomain(TestCase):
    @parameterized.expand([("posthog.com", True), ("eu.posthog.com", True), ("notposthog.com", False), (None, False)])
    def test_is_protected_domain(self, domain: str | None, expected: bool) -> None:
        assert is_protected_domain(domain) is expected


class TestSubjectLength(TestCase):
    @parameterized.expand(
        [
            ("address", {"email": "x@" + "a." * 150_000 + "com"}),
            ("bare domain", {"domain": "a." * 150_000 + "com"}),
        ]
    )
    def test_overlong_input_carries_no_email_or_domain(self, _name: str, kwargs: dict[str, str]) -> None:
        subject = normalize_subject(**kwargs)
        assert subject.email is None and subject.domain is None
