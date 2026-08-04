from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.web_analytics.backend.path_cleaning_suggestions import service
from products.web_analytics.backend.path_cleaning_suggestions.prompts import SuggestedRule, SuggestedRulesResponse
from products.web_analytics.backend.path_cleaning_suggestions.service import (
    AnnotatedRule,
    apply_suggestions_to_team,
    build_suggestion_payload,
    generate_suggestions_for_team,
    validate_and_annotate_rules,
)

SAMPLE_PATHS = [
    ("/users/123/profile", 100),
    ("/users/456/profile", 80),
    ("/users/789/profile", 60),
    ("/about", 40),
]


class TestValidateAndAnnotateRules(BaseTest):
    def test_keeps_valid_rule_with_dense_order_and_annotations(self) -> None:
        rules = [SuggestedRule(regex=r"/users/\d+/profile", alias="/users/<id>/profile", reason="user id")]
        annotated = validate_and_annotate_rules(rules, SAMPLE_PATHS)

        self.assertEqual(len(annotated), 1)
        rule = annotated[0]
        self.assertEqual(rule.order, 0)
        self.assertEqual(rule.match_count, 3)  # 3 of 4 sampled paths match
        self.assertEqual(rule.examples[0], {"before": "/users/123/profile", "after": "/users/<id>/profile"})

    @parameterized.expand(
        [
            ("invalid_regex", r"/users/(\d+/profile", "/users/<id>/profile"),  # unbalanced paren -> re2 error
            ("matches_nothing", r"/orders/\d+$", "/orders/<id>"),  # no /orders path in sample
            ("empty_regex", "", "/x"),
            ("empty_alias", r"/users/\d+", ""),
            # alias backreference with no capture group -> re2 raises on sub; must be dropped, not crash
            ("alias_backreference_no_group", r"/users/\d+/profile", r"/users/\1"),
        ]
    )
    def test_drops_unusable_rules(self, _name: str, regex: str, alias: str) -> None:
        annotated = validate_and_annotate_rules([SuggestedRule(regex=regex, alias=alias)], SAMPLE_PATHS)
        self.assertEqual(annotated, [])

    def test_renumbers_order_densely_when_a_rule_is_dropped(self) -> None:
        rules = [
            SuggestedRule(regex=r"/orders/\d+$", alias="/orders/<id>"),  # dropped: matches nothing
            SuggestedRule(regex=r"/users/\d+/profile", alias="/users/<id>/profile"),  # kept
        ]
        annotated = validate_and_annotate_rules(rules, SAMPLE_PATHS)
        self.assertEqual(len(annotated), 1)
        self.assertEqual(annotated[0].order, 0)


class TestExtractJson(BaseTest):
    @parameterized.expand(
        [
            ("plain", '{"rules": []}'),
            ("fenced", '```json\n{"rules": []}\n```'),
            ("prose_wrapped", 'Here are the rules:\n{"rules": []}\nHope that helps!'),
        ]
    )
    def test_extracts_json_object(self, _name: str, content: str) -> None:
        self.assertEqual(service._extract_json(content), {"rules": []})

    def test_raises_without_json(self) -> None:
        with self.assertRaises(ValueError):
            service._extract_json("no json here")


class TestApplySuggestionsToTeam(BaseTest):
    def _rule(self, regex: str, alias: str) -> AnnotatedRule:
        return AnnotatedRule(regex=regex, alias=alias, order=0, reason="", match_count=1, examples=[])

    def test_appends_to_empty_with_sequential_order(self) -> None:
        self.team.path_cleaning_filters = []
        self.team.save()
        added = apply_suggestions_to_team(
            self.team,
            [self._rule(r"/users/\d+", "/users/<id>"), self._rule(r"/orders/\d+", "/orders/<id>")],
        )
        self.team.refresh_from_db()
        self.assertEqual(added, 2)
        self.assertEqual([f["order"] for f in self.team.path_cleaning_filters], [0, 1])

    def test_merges_without_overwriting_and_dedupes(self) -> None:
        self.team.path_cleaning_filters = [{"regex": r"/users/\d+", "alias": "/users/<id>", "order": 0}]
        self.team.save()
        added = apply_suggestions_to_team(
            self.team,
            [
                self._rule(r"/users/\d+", "/users/<id>"),  # duplicate regex -> skipped
                self._rule(r"/orders/\d+", "/orders/<id>"),  # new -> appended after max order
            ],
        )
        self.team.refresh_from_db()
        self.assertEqual(added, 1)
        self.assertEqual(len(self.team.path_cleaning_filters), 2)
        self.assertEqual(
            self.team.path_cleaning_filters[1], {"regex": r"/orders/\d+", "alias": "/orders/<id>", "order": 1}
        )

    def test_no_rules_is_noop(self) -> None:
        self.team.path_cleaning_filters = [{"regex": r"/a", "alias": "/b", "order": 0}]
        self.team.save()
        added = apply_suggestions_to_team(self.team, [])
        self.team.refresh_from_db()
        self.assertEqual(added, 0)
        self.assertEqual(len(self.team.path_cleaning_filters), 1)


class TestGenerateSuggestionsForTeam(BaseTest):
    def test_skips_inactive_team(self) -> None:
        self.team.path_cleaning_filters = []
        self.team.save()
        with (
            patch.object(service, "has_recent_pageviews", return_value=False),
            patch.object(service, "count_distinct_pathnames") as mock_count,
        ):
            result = generate_suggestions_for_team(self.team, visited_within_days=30)

        self.assertEqual(result.status, "skipped_inactive")
        mock_count.assert_not_called()  # gate short-circuits before any further ClickHouse work

    def test_skips_team_with_existing_rules(self) -> None:
        self.team.path_cleaning_filters = [{"regex": r"/x", "alias": "/y", "order": 0}]
        self.team.save()
        with (
            patch.object(service, "count_distinct_pathnames") as mock_count,
            patch.object(service, "call_llm_for_rules") as mock_llm,
        ):
            result = generate_suggestions_for_team(self.team, include_configured=False, visited_within_days=None)

        self.assertEqual(result.status, "skipped_configured")
        mock_count.assert_not_called()
        mock_llm.assert_not_called()

    def test_skips_low_cardinality(self) -> None:
        self.team.path_cleaning_filters = []
        self.team.save()
        with (
            patch.object(service, "count_distinct_pathnames", return_value=3),
            patch.object(service, "call_llm_for_rules") as mock_llm,
        ):
            result = generate_suggestions_for_team(self.team, min_distinct_paths=50, visited_within_days=None)

        self.assertEqual(result.status, "skipped_low_cardinality")
        self.assertEqual(result.distinct_path_count, 3)
        mock_llm.assert_not_called()

    def test_generates_and_validates(self) -> None:
        self.team.path_cleaning_filters = []
        self.team.save()
        llm_response = SuggestedRulesResponse(
            rules=[
                SuggestedRule(regex=r"/users/\d+/profile", alias="/users/<id>/profile", reason="id"),
                SuggestedRule(regex=r"/orders/\d+$", alias="/orders/<id>"),  # matches nothing -> dropped
            ]
        )
        with (
            patch.object(service, "has_recent_pageviews", return_value=True),  # exercises the gate's happy path
            patch.object(service, "count_distinct_pathnames", return_value=500),
            patch.object(service, "sample_pathnames", return_value=SAMPLE_PATHS),
            patch.object(service, "call_llm_for_rules", return_value=llm_response),
        ):
            result = generate_suggestions_for_team(self.team, visited_within_days=30)

        self.assertEqual(result.status, "generated")
        self.assertEqual(len(result.rules), 1)  # invalid/no-match rule dropped by validation
        payload = build_suggestion_payload(result)
        self.assertEqual(len(payload["rules"]), 1)
        self.assertEqual(payload["distinct_path_count"], 500)
        # Health-issue payloads are readable with just health_issue:read — real sampled paths
        # (the examples) must never be stored in them.
        self.assertNotIn("examples", payload["rules"][0])

    def test_error_is_captured_not_raised(self) -> None:
        self.team.path_cleaning_filters = []
        self.team.save()
        with patch.object(service, "count_distinct_pathnames", side_effect=RuntimeError("clickhouse down")):
            result = generate_suggestions_for_team(self.team, visited_within_days=None)

        self.assertEqual(result.status, "error")
        self.assertIn("clickhouse down", result.error or "")

    def test_visit_gate_failure_is_captured_not_raised(self) -> None:
        # The gate query runs inside the per-team guard: a ClickHouse failure there must
        # produce an error result, not propagate out of a cohort sweep.
        self.team.path_cleaning_filters = []
        self.team.save()
        with patch.object(service, "has_recent_pageviews", side_effect=RuntimeError("clickhouse down")):
            result = generate_suggestions_for_team(self.team, visited_within_days=30)

        self.assertEqual(result.status, "error")
        self.assertIn("clickhouse down", result.error or "")


class TestPathCleaningSuggestionsCheck(BaseTest):
    def _check(self):
        from products.web_analytics.backend.temporal.health_checks.path_cleaning_suggestions import (
            PathCleaningSuggestionsCheck,
        )

        return PathCleaningSuggestionsCheck()

    def _generated_result(self) -> "service.TeamSuggestionResult":
        return service.TeamSuggestionResult(
            team_id=self.team.id,
            status="generated",
            rules=[AnnotatedRule(regex=r"/u/\d+", alias="/u/<id>", order=0, reason="", match_count=2, examples=[])],
            sampled_path_count=4,
            distinct_path_count=500,
            existing_rule_count=0,
            model="claude-haiku-4-5",
        )

    def test_existing_active_issue_is_reemitted_without_llm(self) -> None:
        # If this breaks, every scheduled run re-bills the LLM for every enrolled team and
        # silently replaces suggestions users are mid-review on.
        from posthog.models.health_issue import HealthIssue

        from products.web_analytics.backend.temporal.health_checks import path_cleaning_suggestions as check_module

        self.team.path_cleaning_filters = []
        self.team.save()
        issue, _ = HealthIssue.upsert_issue(
            team_id=self.team.id,
            kind="path_cleaning_suggestions",
            severity=HealthIssue.Severity.INFO,
            payload={
                "rules": [{"regex": "/a", "alias": "/b"}],
                "model": "m",
                "sampled_path_count": 1,
                "distinct_path_count": 100,
            },
            hash_keys=[],
        )
        with (
            self.settings(WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS=[self.team.id]),
            patch.object(check_module, "generate_suggestions_for_team") as mock_generate,
        ):
            results = self._check().detect([self.team.id])

        mock_generate.assert_not_called()
        self.assertEqual(results[self.team.id][0].payload, issue.payload)

    def test_configured_team_is_reported_healthy(self) -> None:
        # A team that configured rules (via apply or by hand) must come back healthy so the
        # framework auto-resolves its suggestion — otherwise applied suggestions linger forever.
        from products.web_analytics.backend.temporal.health_checks import path_cleaning_suggestions as check_module

        self.team.path_cleaning_filters = [{"regex": "/a", "alias": "/b", "order": 0}]
        self.team.save()
        with (
            self.settings(WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS=[self.team.id]),
            patch.object(check_module, "generate_suggestions_for_team") as mock_generate,
        ):
            results = self._check().detect([self.team.id])

        mock_generate.assert_not_called()
        self.assertEqual(results, {})

    def test_empty_generation_stores_nothing(self) -> None:
        # An empty suggestion must not create an issue — it would shadow nothing useful and
        # surface a rule-less banner.
        from products.web_analytics.backend.temporal.health_checks import path_cleaning_suggestions as check_module

        self.team.path_cleaning_filters = []
        self.team.save()
        empty = self._generated_result()
        empty.rules = []
        with (
            self.settings(WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS=[self.team.id]),
            patch.object(check_module, "generate_suggestions_for_team", return_value=empty),
        ):
            results = self._check().detect([self.team.id])

        self.assertEqual(results, {})

    def test_generated_rules_become_an_info_issue(self) -> None:
        from posthog.models.health_issue import HealthIssue

        from products.web_analytics.backend.temporal.health_checks import path_cleaning_suggestions as check_module

        self.team.path_cleaning_filters = []
        self.team.save()
        with (
            self.settings(WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS=[self.team.id]),
            patch.object(check_module, "generate_suggestions_for_team", return_value=self._generated_result()),
        ):
            results = self._check().detect([self.team.id])

        self.assertEqual(results[self.team.id][0].severity, HealthIssue.Severity.INFO)
        self.assertEqual(len(results[self.team.id][0].payload["rules"]), 1)

    def test_team_outside_cohort_is_ignored(self) -> None:
        from products.web_analytics.backend.temporal.health_checks import path_cleaning_suggestions as check_module

        with (
            self.settings(WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS=[]),
            patch.object(check_module, "generate_suggestions_for_team") as mock_generate,
        ):
            results = self._check().detect([self.team.id])

        mock_generate.assert_not_called()
        self.assertEqual(results, {})
