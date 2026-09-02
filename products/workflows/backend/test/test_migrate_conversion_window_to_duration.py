from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _flow(team, name: str, conversion: dict) -> HogFlow:
    return HogFlow.objects.create(
        team=team,
        name=name,
        status="active",
        trigger={"type": "event", "filters": {}},
        exit_condition="exit_only_at_end",
        conversion=conversion,
        actions=[],
        edges=[],
    )


class TestMigrateConversionWindowToDuration(BaseTest):
    @parameterized.expand(
        [
            ("a whole number of days", 129600, "90d"),
            ("a whole number of hours", 60, "1h"),
            ("neither", 90, "90m"),
        ]
    )
    def test_converts_a_window_the_matcher_already_honors(self, _name, minutes, expected):
        flow = _flow(self.team, "convertible", {"filters": [], "window_minutes": minutes})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window": expected}

    @parameterized.expand([("seven days in seconds", 604800), ("thirty days in seconds", 2592000)])
    def test_leaves_a_window_above_the_legacy_ceiling_alone(self, _name, minutes):
        # Converting one of these either way changes what the workflow measures, and which reading is
        # right needs a person. Touching it silently is the failure this guards.
        flow = _flow(self.team, "ambiguous", {"filters": [], "window_minutes": minutes})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window_minutes": minutes}

    def test_dry_run_writes_nothing(self):
        flow = _flow(self.team, "untouched", {"filters": [], "window_minutes": 60})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window_minutes": 60}

    def test_leaves_a_flow_that_already_has_a_window_alone(self):
        flow = _flow(self.team, "already migrated", {"filters": [], "window": "7d"})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window": "7d"}
