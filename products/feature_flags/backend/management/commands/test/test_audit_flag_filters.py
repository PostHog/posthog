import json
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Team

from products.feature_flags.backend.filters_validation import collect_filters_violations
from products.feature_flags.backend.models.feature_flag import FeatureFlag

INVALID_MULTIVARIATE_FILTERS: dict[str, Any] = {
    "groups": [],
    "multivariate": {"variants": [{"key": "a", "rollout_percentage": 50}]},
}


class TestAuditFlagFilters(BaseTest):
    def _create_flag(self, key: str, filters: dict[str, Any], **kwargs: Any) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=kwargs.pop("team", self.team), created_by=self.user, key=key, filters=filters, **kwargs
        )

    def _run(self, *args: str) -> dict[str, Any]:
        # Always scope to this test's team: the local test DB is reused across suites and can
        # carry leftover flags from other tests.
        out = StringIO()
        call_command("audit_flag_filters", "--json", "--team-id", str(self.team.id), *args, stdout=out)
        return json.loads(out.getvalue())

    def _rule(self, report: dict[str, Any], rule_id: str) -> dict[str, Any] | None:
        return next((rule for rule in report["rules"] if rule["rule_id"] == rule_id), None)

    def test_clean_flags_report_no_violations(self) -> None:
        self._create_flag("clean", {"groups": [{"properties": [], "rollout_percentage": 50}]})
        self._create_flag("empty_filters", {})
        self._create_flag("empty_groups", {"groups": []})

        report = self._run()

        assert report["clean"] is True
        assert report["scanned"] == 3
        assert report["flags_with_violations"] == 0
        assert report["rules"] == []

    def test_violations_grouped_by_rule_with_samples(self) -> None:
        structural = self._create_flag("structural", {"groups": [{"properties": [{"type": "person"}]}]})
        cross_field = self._create_flag("cross-field", INVALID_MULTIVARIATE_FILTERS)
        self._create_flag("clean", {"groups": []})

        report = self._run()

        assert report["clean"] is False
        assert report["flags_with_violations"] == 2

        structural_rule = self._rule(report, "structural.groups[].properties[].key.required")
        assert structural_rule is not None
        assert structural_rule["flags_affected"] == 1
        assert structural_rule["sample_flag_ids"] == [structural.id]

        cross_field_rule = self._rule(report, "cross_field.variant_rollout_sum_not_100")
        assert cross_field_rule is not None
        assert cross_field_rule["sample_flag_ids"] == [cross_field.id]
        assert f"team={self.team.id}" in cross_field_rule["sample_details"][0]

    def test_soft_deleted_flags_are_audited(self) -> None:
        flag = self._create_flag("soft-deleted", INVALID_MULTIVARIATE_FILTERS)
        flag.deleted = True
        flag.save()

        report = self._run()

        rule = self._rule(report, "cross_field.variant_rollout_sum_not_100")
        assert rule is not None
        assert rule["sample_flag_ids"] == [flag.id]

    def test_unknown_keys_reported_with_legacy_marker(self) -> None:
        legacy = self._create_flag("legacy", {"groups": [], "holdout_groups": []})
        junk = self._create_flag("junk", {"groups": [], "junk": 1})
        prop_level = self._create_flag(
            "prop-level",
            {"groups": [{"properties": [{"key": "k", "type": "person", "value": "x", "cohort_name": "c"}]}]},
        )

        report = self._run()

        assert report["clean"] is True
        unknown_by_key = {(entry["level"], entry["key"]): entry for entry in report["unknown_keys"]}
        assert unknown_by_key[("filters", "holdout_groups")]["legacy"] is True
        assert unknown_by_key[("filters", "holdout_groups")]["sample_flag_ids"] == [legacy.id]
        assert unknown_by_key[("filters", "junk")]["legacy"] is False
        assert unknown_by_key[("filters", "junk")]["sample_flag_ids"] == [junk.id]
        assert unknown_by_key[("property", "cohort_name")]["sample_flag_ids"] == [prop_level.id]

    def test_unknown_key_counted_once_per_flag(self) -> None:
        self._create_flag(
            "two-groups",
            {"groups": [{"properties": [], "sort_key": "a"}, {"properties": [], "sort_key": "b"}]},
        )

        report = self._run()

        entry = next(e for e in report["unknown_keys"] if e["key"] == "sort_key")
        assert entry["flags_affected"] == 1

    @patch("products.feature_flags.backend.api.filters_schema.logger")
    def test_audit_does_not_log_unknown_keys(self, mock_logger: Any) -> None:
        self._create_flag("junk", {"groups": [], "junk": 1})

        self._run()

        mock_logger.warning.assert_not_called()

    def test_limit_and_samples_options(self) -> None:
        self._create_flag("first", INVALID_MULTIVARIATE_FILTERS)
        self._create_flag("second", INVALID_MULTIVARIATE_FILTERS)

        limited = self._run("--limit", "1")
        assert limited["scanned"] == 1

        sampled = self._run("--samples", "1")
        rule = self._rule(sampled, "cross_field.variant_rollout_sum_not_100")
        assert rule is not None
        assert rule["flags_affected"] == 2
        assert len(rule["sample_flag_ids"]) == 1

    def test_team_id_restricts_scan(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._create_flag("other-team", INVALID_MULTIVARIATE_FILTERS, team=other_team)
        self._create_flag("this-team", {"groups": []})

        report = self._run()

        assert report["scanned"] == 1
        assert report["clean"] is True

    def test_team_id_maps_environment_to_root_team(self) -> None:
        env_team = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="env"
        )
        self._create_flag("root-team-flag", INVALID_MULTIVARIATE_FILTERS)

        out = StringIO()
        call_command("audit_flag_filters", "--json", "--team-id", str(env_team.id), stdout=out)
        report = json.loads(out.getvalue())

        # A false "0 flags scanned, clean" here means the manager stopped resolving
        # environment team ids to the project root.
        assert report["scanned"] == 1
        assert report["clean"] is False

    def test_validator_crash_becomes_violation_not_dead_scan(self) -> None:
        crashing = self._create_flag("crashing", {"groups": []})
        self._create_flag("clean", {"groups": []})

        real = collect_filters_violations

        def crash_on_first(filters: Any, **kwargs: Any) -> Any:
            if kwargs.get("context", {}).get("flag_id") == crashing.id:
                raise TypeError("unhashable type: 'list'")
            return real(filters, **kwargs)

        with patch(
            "products.feature_flags.backend.management.commands.audit_flag_filters.collect_filters_violations",
            side_effect=crash_on_first,
        ):
            report = self._run()

        assert report["scanned"] == 2
        rule = self._rule(report, "structural.filters.internal_error")
        assert rule is not None
        assert rule["sample_flag_ids"] == [crashing.id]

    def test_console_output_summarizes(self) -> None:
        self._create_flag("cross-field", INVALID_MULTIVARIATE_FILTERS)
        out = StringIO()

        call_command("audit_flag_filters", "--team-id", str(self.team.id), stdout=out)

        output = out.getvalue()
        assert "1 with violations" in output
        assert "cross_field.variant_rollout_sum_not_100" in output

    def test_console_output_reports_clean_scan(self) -> None:
        self._create_flag("clean", {"groups": []})
        out = StringIO()

        call_command("audit_flag_filters", "--team-id", str(self.team.id), stdout=out)

        assert "No violations found." in out.getvalue()

    def test_repeated_rule_counts_flag_once_but_all_violations(self) -> None:
        self._create_flag(
            "double",
            {
                "groups": [
                    {
                        "properties": [
                            {"key": "a", "type": "person", "operator": "in", "value": [1]},
                            {"key": "b", "type": "person", "operator": "in", "value": [2]},
                        ]
                    }
                ]
            },
        )

        report = self._run()

        rule = self._rule(report, "cross_field.in_not_in_requires_cohort")
        assert rule is not None
        assert rule["flags_affected"] == 1
        assert rule["total_violations"] == 2

    @patch("products.feature_flags.backend.management.commands.audit_flag_filters.MAX_TRACKED_UNKNOWN_KEYS", 1)
    def test_console_output_reports_untracked_keys(self) -> None:
        self._create_flag("many-junk-keys", {"groups": [], "junk_a": 1, "junk_b": 2})
        out = StringIO()

        call_command("audit_flag_filters", "--team-id", str(self.team.id), stdout=out)

        assert "tracking cap" in out.getvalue()

    @parameterized.expand(
        [
            ("negative_limit", ["--limit", "-1"]),
            ("negative_samples", ["--samples", "-1"]),
            ("nonexistent_team", ["--team-id", "999999999"]),
        ]
    )
    def test_invalid_options_rejected(self, _name: str, args: list[str]) -> None:
        self._create_flag("clean", {"groups": []})

        with self.assertRaises(CommandError):
            call_command("audit_flag_filters", *args, stdout=StringIO())

    def test_console_output_escapes_control_sequences(self) -> None:
        self._create_flag(
            "escape-junk",
            {"groups": [], "payloads": {"\x1b]0;evil\x07": "1"}, "junk\x1b[31mkey": 1},
        )
        out = StringIO()

        call_command("audit_flag_filters", "--team-id", str(self.team.id), stdout=out)

        output = out.getvalue()
        assert "\x1b" not in output
        assert "\x07" not in output
        assert "�" in output

    @patch("products.feature_flags.backend.management.commands.audit_flag_filters.MAX_TRACKED_UNKNOWN_KEYS", 1)
    def test_unknown_key_tracking_is_capped(self) -> None:
        self._create_flag("many-junk-keys", {"groups": [], "junk_a": 1, "junk_b": 2})

        report = self._run()

        assert len(report["unknown_keys"]) == 1
        assert report["untracked_unknown_keys"] == 1
