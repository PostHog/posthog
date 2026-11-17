from collections.abc import Callable
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_program

from posthog.models import Team

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags import registry, runner
from products.error_tracking.backend.logic.issue_tags.correction import UnknownIssueTagError, correct_issue_tag
from products.error_tracking.backend.logic.issue_tags.enabled import enabled_issue_tag_definitions
from products.error_tracking.backend.logic.issue_tags.runner import IssueTaggingSkipReason, TaggerRun, run_issue_taggers
from products.error_tracking.backend.logic.issue_tags.taggers.rule import RuleTagger
from products.error_tracking.backend.logic.rules import MAX_SEVERITY_RULE_BYTECODE_OPS, compile_filter_bytecode
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag, ErrorTrackingIssueTagRule
from products.event_definitions.backend.models import PropertyDefinition, PropertyType

Source = ErrorTrackingIssueTag.Source

DECIDE = "products.error_tracking.backend.logic.issue_tags.taggers.jev.ml_inference.decide_when_available"

# No $exception_list, so the event has no stack trace.
BIG_UNHANDLED_ORDER: dict[str, object] = {"revenue": 25, "$exception_handled": False, "$lib": "posthog-python"}


def _program(source: str) -> list[Any]:
    return create_bytecode(parse_program(source)).bytecode


def _event_filter(key: str, operator: str, value: Any) -> dict[str, Any]:
    leaf = {"key": key, "type": "event", "operator": operator, "value": value}
    return {"type": "AND", "values": [{"type": "AND", "values": [leaf]}]}


@patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: True)
class TestIssueTagRules(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        for name, property_type in (("revenue", PropertyType.Numeric), ("$exception_handled", PropertyType.Boolean)):
            PropertyDefinition.objects.create(
                team=self.team, name=name, type=PropertyDefinition.Type.EVENT, property_type=property_type
            )
        self.big_order = self._rule("Big order", _event_filter("revenue", "gt", 10), order_key=1, version=2)
        self.unhandled = self._rule("Unhandled", _event_filter("$exception_handled", "exact", ["false"]), order_key=2)

    @parameterized.expand(
        [
            ("both_match", BIG_UNHANDLED_ORDER, ["big_order", "unhandled"]),
            ("neither_matches", {"revenue": 5, "$exception_handled": True}, []),
            ("one_matches", {"revenue": 25, "$exception_handled": True}, ["big_order"]),
        ]
    )
    def test_a_matching_rule_applies_its_label_and_a_miss_writes_nothing(
        self, _name: str, event_properties: dict[str, object], matching_rules: list[str]
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with patch(DECIDE) as decide:
            result = run_issue_taggers(self.team.id, issue.id, lambda team: event_properties)

        decide.assert_not_called()
        assert result == (TaggerRun(source=Source.RULE), TaggerRun(source=Source.JEV))
        rows = ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue)
        rules = [getattr(self, name) for name in matching_rules]
        assert {(row.key, row.value, row.source, row.question_version, row.model) for row in rows} == {
            (rule.key, True, Source.RULE, rule.version, str(rule.id)) for rule in rules
        }

    def test_a_rule_with_an_empty_filter_applies_to_every_issue(self) -> None:
        every_issue = self._rule("Every issue", {"type": "AND", "values": []}, order_key=3)
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        run_issue_taggers(self.team.id, issue.id, lambda team: {})

        assert list(
            ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue).values_list("key", "value")
        ) == [(every_issue.key, True)]

    def test_a_rule_match_does_not_replace_a_manual_removal(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        correct_issue_tag(
            self.team.id, issue.id, self.big_order.key, applied=False, user=self.user, was_impersonated=False
        )

        run_issue_taggers(self.team.id, issue.id, lambda team: BIG_UNHANDLED_ORDER)

        tags = ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue)
        assert dict(tags.values_list("key", "source")) == {
            self.big_order.key: Source.MANUAL,
            self.unhandled.key: Source.RULE,
        }
        assert tags.get(key=self.big_order.key).value is False

    def test_a_rule_applies_to_and_shows_for_its_own_team_only(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        other_issue = ErrorTrackingIssue.objects.create(team=other_team)

        run_issue_taggers(other_team.id, other_issue.id, lambda team: BIG_UNHANDLED_ORDER)

        assert not ErrorTrackingIssueTag.objects.for_team(other_team.id).filter(issue=other_issue).exists()
        code_keys = [definition.key for definition in registry.ISSUE_TAG_DEFINITIONS]
        assert [definition.key for definition in enabled_issue_tag_definitions(self.team.id)] == [
            *code_keys,
            self.big_order.key,
            self.unhandled.key,
        ]
        assert [definition.key for definition in enabled_issue_tag_definitions(other_team.id)] == code_keys
        with self.assertRaises(UnknownIssueTagError):
            correct_issue_tag(
                other_team.id, other_issue.id, self.big_order.key, applied=True, user=self.user, was_impersonated=False
            )

    @parameterized.expand(
        [
            (
                "raises_on_this_event",
                lambda team_id: compile_filter_bytecode(
                    team_id, _event_filter("signed_up_at", "is_date_before", "2026-01-01")
                ),
                timedelta(seconds=60),
                timedelta(seconds=60),
                None,
                True,
            ),
            (
                "runs_past_its_timeout",
                lambda team_id: _program("while (true) {}"),
                timedelta(milliseconds=200),
                timedelta(seconds=60),
                None,
                True,
            ),
            (
                "runs_out_the_issue_budget",
                lambda team_id: _program("while (true) {}"),
                timedelta(seconds=60),
                timedelta(milliseconds=200),
                None,
                False,
            ),
            (
                "bytecode_over_the_size_limit",
                lambda team_id: ["_H", 1, *([None] * MAX_SEVERITY_RULE_BYTECODE_OPS)],
                timedelta(seconds=60),
                timedelta(seconds=60),
                f"Rule bytecode has {MAX_SEVERITY_RULE_BYTECODE_OPS + 2} operations, maximum is {MAX_SEVERITY_RULE_BYTECODE_OPS}",
                True,
            ),
        ]
    )
    def test_disables_a_rule_only_for_a_fault_in_its_bytecode(
        self,
        _name: str,
        bytecode: Callable[[int], list[Any]],
        rule_timeout: timedelta,
        issue_budget: timedelta,
        disabled_message: str | None,
        other_rules_run: bool,
    ) -> None:
        broken = self._rule("Broken", {}, order_key=0, bytecode=bytecode(self.team.id))
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        tagger = RuleTagger(rule_timeout=rule_timeout, issue_budget=issue_budget)

        with patch.object(runner, "TAGGERS", (tagger,)):
            result = run_issue_taggers(self.team.id, issue.id, lambda team: BIG_UNHANDLED_ORDER)

        broken.refresh_from_db()
        applied = ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue).values_list("key", flat=True)
        listed = {definition.key for definition in enabled_issue_tag_definitions(self.team.id)}
        assert result == (TaggerRun(source=Source.RULE),)
        assert ((broken.disabled_data or {}).get("message"), set(applied), broken.key in listed) == (
            disabled_message,
            {self.big_order.key, self.unhandled.key} if other_rules_run else set(),
            disabled_message is None,
        )

    def test_reads_no_rules_while_issue_tags_are_off(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        load_event_properties = MagicMock(return_value=BIG_UNHANDLED_ORDER)

        with patch.object(team_flags, "feature_enabled_or_false", return_value=False), self.assertNumQueries(0):
            definitions = enabled_issue_tag_definitions(self.team.id)
            result = run_issue_taggers(self.team.id, issue.id, load_event_properties)

        assert (definitions, result) == ((), IssueTaggingSkipReason.DISABLED)
        load_event_properties.assert_not_called()

    def _rule(
        self,
        label: str,
        filters: dict[str, Any],
        *,
        order_key: int,
        version: int = 1,
        bytecode: list[Any] | None = None,
    ) -> ErrorTrackingIssueTagRule:
        return ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team,
            label=label,
            filters=filters,
            bytecode=compile_filter_bytecode(self.team.id, filters) if bytecode is None else bytecode,
            order_key=order_key,
            version=version,
        )
