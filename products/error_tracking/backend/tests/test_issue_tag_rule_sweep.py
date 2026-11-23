import uuid
import itertools
import dataclasses
from collections.abc import Callable
from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.db.models import F, QuerySet
from django.utils import timezone

from parameterized import parameterized

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG
from products.error_tracking.backend.logic.issue_tags.sweep import (
    RuleSweep,
    TagRuleSweepSkipReason,
    TeamTagRuleSweep,
    sweep_team_tag_rules,
)
from products.error_tracking.backend.logic.rules import compile_filter_bytecode
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueTag,
    ErrorTrackingIssueTagRule,
    sync_issues_to_clickhouse,
)

Source = ErrorTrackingIssueTag.Source

QUERY = "products.error_tracking.backend.logic.issue_tags.sweep.execute_hogql_query"
WINDOW = timedelta(hours=25)


def rule_filters(key: str, operator: str, value: str) -> dict:
    return {
        "type": "AND",
        "values": [{"type": "AND", "values": [{"key": key, "type": "event", "operator": operator, "value": value}]}],
    }


def create_tag_rule(team_id: int, filters: dict) -> ErrorTrackingIssueTagRule:
    return ErrorTrackingIssueTagRule.objects.for_team(team_id).create(
        team_id=team_id,
        label="Checkout",
        filters=filters,
        bytecode=compile_filter_bytecode(team_id, filters),
        order_key=1,
    )


CHECKOUT = rule_filters("$pathname", "icontains", "/checkout")


class TestSweepTeamTagRules(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enabled_flags = {ISSUE_TAGS_FLAG}
        flags = patch.object(
            team_flags, "feature_enabled_or_false", new=lambda flag, *args, **kwargs: flag in self.enabled_flags
        )
        flags.start()
        self.addCleanup(flags.stop)
        self.rule = create_tag_rule(self.team.id, CHECKOUT)
        self.end = timezone.now()

    def test_labels_each_issue_with_the_rules_that_its_exceptions_match(self) -> None:
        home = create_tag_rule(self.team.id, rule_filters("$pathname", "exact", "/home"))
        later_match = self._issue()
        self._exception(later_match, "/home", hours_ago=3)
        self._exception(later_match, "/checkout/pay", hours_ago=2)
        home_only = self._issue()
        self._exception(home_only, "/home", hours_ago=2)
        match_before_window = self._issue()
        self._exception(match_before_window, "/checkout/pay", hours_ago=30)
        self._exception(self._issue(), "/settings", hours_ago=2)
        flush_persons_and_events()

        result = self._sweep()

        assert isinstance(result, TeamTagRuleSweep)
        assert (result.dry_run, result.matching_issues, result.rules_skipped, result.truncated) == (False, 2, 0, False)
        # Two rules made in one test can share a created_at, so the sweep's rule order is not fixed here.
        assert sorted(result.rules, key=lambda rule: rule.rule_id) == sorted(
            [
                RuleSweep(rule_id=self.rule.id, matching_issues=1, labels_to_write=1, labels_written=1),
                RuleSweep(rule_id=home.id, matching_issues=2, labels_to_write=2, labels_written=2),
            ],
            key=lambda rule: rule.rule_id,
        )
        assert sorted(self._answers()) == sorted(
            [
                (later_match.id, self.rule.key, True, Source.RULE, str(self.rule.id), 1),
                (later_match.id, home.key, True, Source.RULE, str(home.id), 1),
                (home_only.id, home.key, True, Source.RULE, str(home.id), 1),
            ]
        )

    def test_a_dry_run_counts_the_labels_and_writes_none(self) -> None:
        issue = self._issue()
        self._exception(issue, "/checkout/pay", hours_ago=2)
        flush_persons_and_events()

        result = self._sweep(dry_run=True)

        assert result == self._result(dry_run=True, matching=1, to_write=1, written=0)
        assert self._answers() == []

    def test_an_exception_counts_for_the_issue_that_its_fingerprint_maps_to(self) -> None:
        merged = self._issue()
        target = self._issue()
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=target, fingerprint="merged-fingerprint")
        sync_issues_to_clickhouse(issue_ids=[target.id], team_id=self.team.id)
        self._exception(merged, "/checkout/pay", hours_ago=2, fingerprint="merged-fingerprint")
        flush_persons_and_events()

        result = self._sweep()

        assert result == self._result(dry_run=False, matching=1, to_write=1, written=1)
        assert self._answers() == [(target.id, self.rule.key, True, Source.RULE, str(self.rule.id), 1)]

    def test_an_issue_deleted_during_the_run_does_not_stop_the_other_labels(self) -> None:
        deleted = self._issue()
        self._exception(deleted, "/checkout/pay", hours_ago=2)
        kept = self._issue()
        self._exception(kept, "/checkout/pay", hours_ago=2)
        flush_persons_and_events()

        result = self._sweep(on_progress=lambda: ErrorTrackingIssue.objects.filter(id=deleted.id).delete())

        assert result == self._result(dry_run=False, matching=2, to_write=2, written=1)
        assert self._answers() == [(kept.id, self.rule.key, True, Source.RULE, str(self.rule.id), 1)]

    def test_a_person_who_removed_the_label_keeps_the_answer(self) -> None:
        issue = self._issue()
        self._exception(issue, "/checkout/pay", hours_ago=2)
        flush_persons_and_events()
        ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
            team=self.team, issue=issue, key=self.rule.key, value=False, source=Source.MANUAL, question_version=1
        )

        result = self._sweep()

        assert result == self._result(dry_run=False, matching=1, to_write=0, written=0)
        assert self._answers() == [(issue.id, self.rule.key, False, Source.MANUAL, None, 1)]

    @parameterized.expand(
        [
            ("deleted", lambda rules: rules.delete(), 0),
            ("edited", lambda rules: rules.update(version=F("version") + 1), 0),
            ("disabled", lambda rules: rules.update(disabled_data={"message": "broken"}), 0),
            ("deleted_between_labels", lambda rules: rules.delete(), 1),
        ]
    )
    def test_a_rule_changed_during_the_run_stops_its_labels(
        self, _name: str, change: Callable[[QuerySet[ErrorTrackingIssueTagRule]], object], labels_before_change: int
    ) -> None:
        for _ in range(2):
            self._exception(self._issue(), "/checkout/pay", hours_ago=2)
        flush_persons_and_events()
        rules = ErrorTrackingIssueTagRule.objects.for_team(self.team.id).filter(id=self.rule.id)
        progress = itertools.count()

        # The sweep reports progress after its query and after each label, which is where a person's change lands.
        def on_progress() -> None:
            if next(progress) == labels_before_change:
                change(rules)

        result = self._sweep(on_progress=on_progress)

        assert result == self._result(dry_run=False, matching=2, to_write=2, written=labels_before_change)
        assert len(self._answers()) == labels_before_change

    def test_a_team_without_issue_tags_reads_no_rule_or_event(self) -> None:
        self.enabled_flags.clear()

        with self.assertNumQueries(0), patch(QUERY, side_effect=AssertionError("flag is off, so no event read")):
            result = self._sweep()

        assert result == TagRuleSweepSkipReason.DISABLED

    def test_a_rule_on_the_exception_list_is_skipped_without_a_query(self) -> None:
        self.rule.delete()
        create_tag_rule(self.team.id, rule_filters("$exception_list", "icontains", "Timeout"))

        with patch(QUERY, side_effect=AssertionError("the only rule is skipped, so no event read")):
            result = self._sweep()

        assert isinstance(result, TeamTagRuleSweep)
        assert (result.rules, result.rules_skipped) == ((), 1)

    def _sweep(
        self, on_progress: Callable[[], object] = lambda: None, dry_run: bool = False
    ) -> TeamTagRuleSweep | TagRuleSweepSkipReason:
        result = sweep_team_tag_rules(
            self.team.id, start=self.end - WINDOW, end=self.end, dry_run=dry_run, on_progress=on_progress
        )
        # The measured query time differs on every run.
        if isinstance(result, TeamTagRuleSweep):
            return dataclasses.replace(result, query_duration=timedelta(0))
        return result

    def _result(self, *, dry_run: bool, matching: int, to_write: int, written: int) -> TeamTagRuleSweep:
        return TeamTagRuleSweep(
            dry_run=dry_run,
            rules=(
                RuleSweep(
                    rule_id=self.rule.id, matching_issues=matching, labels_to_write=to_write, labels_written=written
                ),
            ),
            rules_skipped=0,
            matching_issues=matching,
            query_duration=timedelta(0),
        )

    def _issue(self) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team, issue=issue, fingerprint=f"fingerprint-{issue.id}"
        )
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.id)
        return issue

    def _exception(
        self, issue: ErrorTrackingIssue, pathname: str, *, hours_ago: int, fingerprint: str | None = None
    ) -> None:
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id="user",
            properties={
                "$exception_issue_id": str(issue.id),
                "$exception_fingerprint": fingerprint or f"fingerprint-{issue.id}",
                "$pathname": pathname,
            },
            timestamp=self.end - timedelta(hours=hours_ago),
        )

    def _answers(self) -> list[tuple[uuid.UUID, str, bool | None, str, str | None, int]]:
        tags = ErrorTrackingIssueTag.objects.for_team(self.team.id).order_by("issue_id", "key")
        return list(tags.values_list("issue_id", "key", "value", "source", "model", "question_version"))
