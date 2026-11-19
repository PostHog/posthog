from collections.abc import Callable
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_program

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import (
    PropertyAccessLevel,
    RestrictedPropertyNames,
    UpsertPropertyAccessControlInput,
)
from products.error_tracking.backend.facade import api as issue_facade
from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags import registry, runner
from products.error_tracking.backend.logic.issue_tags.correction import UnknownIssueTagError, correct_issue_tag
from products.error_tracking.backend.logic.issue_tags.enabled import (
    _reads_restricted_property,
    enabled_issue_tag_definitions,
)
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


def _no_event_read(team: Team) -> dict[str, object]:
    raise AssertionError("the event must not be read")


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

        with patch(DECIDE, side_effect=AssertionError("no model call")):
            result = run_issue_taggers(self.team.id, issue.id, lambda team: event_properties)

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

    def test_a_rule_match_writes_no_activity_and_a_correction_does_not_log_it(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        activity = ActivityLog.objects.filter(team_id=self.team.id, scope="ErrorTrackingIssue", item_id=str(issue.id))

        run_issue_taggers(self.team.id, issue.id, lambda team: BIG_UNHANDLED_ORDER)
        assert not activity.exists()

        correct_issue_tag(
            self.team.id, issue.id, self.big_order.key, applied=False, user=self.user, was_impersonated=False
        )
        assert [change for entry in activity for change in (entry.detail or {}).get("changes", [])] == [
            {
                "type": "ErrorTrackingIssue",
                "action": "created",
                "field": "tag",
                "before": None,
                "after": {"key": self.big_order.key, "value": False, "source": Source.MANUAL},
            }
        ]

    def test_a_rule_applies_to_and_shows_for_its_own_team_only(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        other_issue = ErrorTrackingIssue.objects.create(team=other_team)

        run_issue_taggers(other_team.id, other_issue.id, lambda team: BIG_UNHANDLED_ORDER)

        assert not ErrorTrackingIssueTag.objects.for_team(other_team.id).filter(issue=other_issue).exists()
        code_keys = [definition.key for definition in registry.ISSUE_TAG_DEFINITIONS]
        assert [definition.key for definition in enabled_issue_tag_definitions(self.team.id, self.user)] == [
            *code_keys,
            self.big_order.key,
            self.unhandled.key,
        ]
        assert [definition.key for definition in enabled_issue_tag_definitions(other_team.id, self.user)] == code_keys
        with self.assertRaises(UnknownIssueTagError):
            correct_issue_tag(
                other_team.id, other_issue.id, self.big_order.key, applied=True, user=self.user, was_impersonated=False
            )

    def test_hides_a_rule_label_from_a_member_who_may_not_read_its_property(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        run_issue_taggers(self.team.id, issue.id, lambda team: BIG_UNHANDLED_ORDER)
        other = User.objects.create_and_join(self.organization, "other@example.com", "password")
        outsider = User.objects.create(email="outsider@example.com")
        self._restrict_revenue_for_the_member()
        code_keys = {definition.key for definition in registry.ISSUE_TAG_DEFINITIONS}

        def visible(user: User) -> tuple[set[str], set[str]]:
            tags = issue_facade.get_issue(issue.id, self.team.id, with_tags_for=user).tags or []
            listed = issue_facade.list_issue_tag_definitions(self.team.id, user)
            return {tag.key for tag in tags}, {definition.key for definition in listed} - code_keys

        assert visible(self.user) == ({self.unhandled.key}, {self.unhandled.key})
        both = {self.big_order.key, self.unhandled.key}
        assert visible(other) == (both, both)
        assert visible(outsider) == (set(), set())
        for user in (self.user, outsider):
            with self.assertRaises(UnknownIssueTagError):
                correct_issue_tag(
                    self.team.id, issue.id, self.big_order.key, applied=False, user=user, was_impersonated=False
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
                "not_hogvm_bytecode",
                lambda team_id: ["not bytecode"],
                timedelta(seconds=60),
                timedelta(seconds=60),
                "Rule bytecode is not HogVM bytecode",
                True,
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
        listed = {definition.key for definition in enabled_issue_tag_definitions(self.team.id, self.user)}
        assert result == (TaggerRun(source=Source.RULE),)
        assert ((broken.disabled_data or {}).get("message"), set(applied), broken.key in listed) == (
            disabled_message,
            {self.big_order.key, self.unhandled.key} if other_rules_run else set(),
            disabled_message is None,
        )

    def test_reads_no_rules_while_issue_tags_are_off(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with patch.object(team_flags, "feature_enabled_or_false", return_value=False), self.assertNumQueries(0):
            definitions = enabled_issue_tag_definitions(self.team.id, self.user)
            result = run_issue_taggers(self.team.id, issue.id, _no_event_read)

        assert (definitions, result) == ((), IssueTaggingSkipReason.DISABLED)

    def _restrict_revenue_for_the_member(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        upsert_property_access_control(
            team_id=self.team.id,
            created_by_id=self.user.id,
            input=UpsertPropertyAccessControlInput(
                property_definition_id=str(PropertyDefinition.objects.get(team=self.team, name="revenue").id),
                access_level=PropertyAccessLevel.NONE,
                organization_member_id=self.organization_membership.id,
            ),
        )

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


NONE: dict[str, frozenset[str]] = {"event": frozenset(), "person": frozenset()}
PLAN = frozenset({"plan"})
GROUP_PLAN = {"key": "plan", "type": "group", "group_type_index": 0}


def _filter(leaf: dict[str, Any]) -> dict[str, Any]:
    return {"type": "AND", "values": [{"type": "AND", "values": [leaf]}]}


def _events(*names: str) -> RestrictedPropertyNames:
    return RestrictedPropertyNames(event=frozenset(names), person=frozenset())


def _people(*names: str) -> RestrictedPropertyNames:
    return RestrictedPropertyNames(event=frozenset(), person=frozenset(names))


class TestRuleFilterReadsRestrictedProperty(SimpleTestCase):
    @parameterized.expand(
        [
            ("same_name", _event_filter("revenue", "gt", 10), _events("revenue"), True),
            (
                "parent_of_a_restricted_path",
                _event_filter("payload", "is_set", "is_set"),
                _events("payload.secret"),
                True,
            ),
            (
                "child_of_a_restricted_name",
                _event_filter("customer.ssn", "is_set", "is_set"),
                _events("customer"),
                True,
            ),
            ("unrelated_name", _event_filter("revenue", "gt", 10), _events("plan"), False),
            ("person_property", _filter({"key": "email", "type": "person"}), _people("email"), True),
            ("event_name_on_a_person_filter", _filter({"key": "email", "type": "person"}), _events("email"), False),
            ("group_property_of_its_type", _filter(GROUP_PLAN), RestrictedPropertyNames(**NONE, group={0: PLAN}), True),
            (
                "group_property_of_another_type",
                _filter(GROUP_PLAN),
                RestrictedPropertyNames(**NONE, group={1: PLAN}),
                False,
            ),
            ("hogql_filter", _filter({"type": "hogql", "key": "properties.plan"}), _events("x"), True),
            ("filter_without_a_key", _filter({"type": "event", "value": 1}), _events("x"), True),
            ("value_that_is_not_a_filter", {"type": "AND", "values": ["revenue"]}, _events("x"), True),
        ]
    )
    def test_follows_dot_paths_and_fails_closed(
        self, _name: str, filters: dict[str, Any], restricted: RestrictedPropertyNames, expected: bool
    ) -> None:
        assert _reads_restricted_property(filters, restricted) is expected
