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
ORDER = [Surface.SIGNUP, Surface.APP, Surface.AI_GATEWAY, Surface.EMAIL_CODE, Surface.SIGNUP_RISK]
LETTERS = {Surface.EMAIL_CODE: "E", Surface.SIGNUP_RISK: "E"}
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def _pattern_rule(value: str, **overrides: str) -> dict[str, str]:
    return {
        "id": "pattern",
        "targetType": "email_pattern",
        "targetValue": value,
        "effect": "block",
        "scope": "all_access",
        **overrides,
    }


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
            ("pattern matches everyone", _pattern_rule("*@*")),
            ("pattern local part has two literals", _pattern_rule("ab*@*")),
            ("pattern names only a domain", _pattern_rule("*@gmail.com")),
            ("pattern has four wildcards", _pattern_rule("abc*d*e*f*@example.com")),
            ("pattern has two @", _pattern_rule("abc@def@example.com")),
            ("pattern domain has no literal label", _pattern_rule("abc*@*.*")),
            ("pattern domain has an empty label", _pattern_rule("abc*@example..com")),
            ("pattern domain has an underscore", _pattern_rule("abc*@exa_mple.com")),
            ("pattern has a space", _pattern_rule("abc *@example.com")),
            ("pattern exemption", _pattern_rule("abc*@example.com", effect="exempt", scope="email_code")),
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


class TestEmailPatterns(TestCase):
    @parameterized.expand(
        [
            ("head and tail never overlap", "abc*bc@example.com", "abc@example.com", False),
            ("a middle segment never overlaps the tail", "abc*_*_x@example.com", "abc_x@example.com", False),
            ("three wildcards", "bot*_*@*.example.com", "bot12_x@mail.example.com", True),
            ("segments match in order", "bot*_*@*.example.com", "bot12@x_mail.example.com", False),
        ]
    )
    def test_pattern_block(self, _name: str, pattern: str, email: str, blocked: bool) -> None:
        rule = SnapshotRule.from_wire(_pattern_rule(pattern))
        assert rule is not None
        decided = deciding_rule(build_index([rule]), normalize_subject(email=email), Surface.APP, NOW)
        assert (decided is not None) is blocked

    def test_oldest_rule_decides_across_patterns_and_exact_addresses(self) -> None:
        exact = SnapshotRule.from_wire(
            {
                "id": "b",
                "targetType": "email",
                "targetValue": "abuser1@example.com",
                "effect": "block",
                "scope": "all_access",
            }
        )
        pattern = SnapshotRule.from_wire(_pattern_rule("abuser*@example.com", id="a"))
        assert exact is not None and pattern is not None
        decided = deciding_rule(
            build_index([exact, pattern]), normalize_subject(email="abuser1@example.com"), Surface.APP, NOW
        )
        assert decided is not None and decided.id == "a"


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
