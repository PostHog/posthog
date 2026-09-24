from io import StringIO
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision


def _flow(team: Team, name: str, conversion: dict[str, Any]) -> HogFlow:
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


def _template(team: Team, conversion: dict[str, Any]) -> HogFlowTemplate:
    return HogFlowTemplate.objects.create(team=team, name="template", scope="team", conversion=conversion)


class TestMigrateConversionWindowToDuration(BaseTest):
    @parameterized.expand(
        [
            ("a whole number of days", 129600, "90d"),
            ("a whole number of hours", 60, "1h"),
            ("neither", 90, "90m"),
        ]
    )
    def test_converts_a_window_the_matcher_already_honors(self, _name: str, minutes: int, expected: str) -> None:
        flow = _flow(self.team, "convertible", {"filters": [], "window_minutes": minutes})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window": expected}

    @parameterized.expand([("seven days in seconds", 604800), ("thirty days in seconds", 2592000)])
    def test_leaves_a_window_above_the_legacy_ceiling_alone(self, _name: str, minutes: int) -> None:
        # Converting one of these either way changes what the workflow measures, and which reading is
        # right needs a person. Touching it silently is the failure this guards.
        flow = _flow(self.team, "ambiguous", {"filters": [], "window_minutes": minutes})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window_minutes": minutes}

    @parameterized.expand(
        [
            ("a number", 7),
            ("null", None),
            ("an empty string", ""),
            ("a string the duration grammar rejects", "1 week"),
            ("an ISO-8601 duration", "P7D"),
            ("a duration of zero", "0d"),
        ]
    )
    def test_converts_over_a_window_that_is_not_a_usable_duration(self, _name: str, window: object) -> None:
        # The matcher honors `window` only when the shared grammar parses it to a positive value, so
        # each of these already falls through to the legacy value. Skipping the row here would let the
        # strip pass delete the only readable window.
        flow = _flow(self.team, "junk window", {"filters": [], "window": window, "window_minutes": 60})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window": "1h"}

    def test_dry_run_writes_nothing(self) -> None:
        flow = _flow(self.team, "untouched", {"filters": [], "window_minutes": 60})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window_minutes": 60}

    def test_leaves_a_flow_that_already_has_a_window_alone(self) -> None:
        flow = _flow(self.team, "already migrated", {"filters": [], "window": "7d"})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window": "7d"}

    def test_converts_the_draft_copy_of_a_conversion(self) -> None:
        # A draft carries its own conversion, so leaving it behind puts the deprecated field back on
        # the live row the moment someone publishes.
        flow = _flow(self.team, "with draft", {"filters": [], "window_minutes": 60})
        flow.draft = {"conversion": {"filters": [], "window_minutes": 1440}}
        flow.save()

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window": "1h"}
        assert flow.draft == {"conversion": {"filters": [], "window": "1d"}}

    def test_converts_a_revision_snapshot(self) -> None:
        # Restoring a snapshot copies it back into the draft, so an unmigrated one reintroduces the field.
        flow = _flow(self.team, "with revision", {"filters": [], "window": "7d"})
        with team_scope(self.team.id):
            revision = HogFlowRevision.objects.create(
                team=self.team,
                hog_flow=flow,
                version=1,
                content={"conversion": {"filters": [], "window_minutes": 1440}},
            )

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        with team_scope(self.team.id):
            revision.refresh_from_db()
        assert revision.content == {"conversion": {"filters": [], "window": "1d"}}

    def test_converts_a_template(self) -> None:
        # A new workflow copies the template's conversion, and the flow API drops window_minutes, so an
        # unmigrated template hands every workflow built from it the default window instead of its own.
        template = _template(self.team, {"filters": [], "window_minutes": 2880})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        template.refresh_from_db()
        assert template.conversion == {"filters": [], "window": "2d"}

    def test_leaves_an_ambiguous_revision_snapshot_alone(self) -> None:
        flow = _flow(self.team, "ambiguous revision", {"filters": [], "window": "7d"})
        with team_scope(self.team.id):
            revision = HogFlowRevision.objects.create(
                team=self.team,
                hog_flow=flow,
                version=1,
                content={"conversion": {"filters": [], "window_minutes": 604800}},
            )

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True)

        with team_scope(self.team.id):
            revision.refresh_from_db()
        assert revision.content == {"conversion": {"filters": [], "window_minutes": 604800}}


class TestStripInert(BaseTest):
    @parameterized.expand(
        [
            ("null", None),
            ("zero", 0),
            ("above the legacy ceiling, which the matcher clamped anyway", 604800),
        ]
    )
    def test_strips_a_value_that_cannot_change_what_the_workflow_measures(
        self, _name: str, minutes: int | None
    ) -> None:
        flow = _flow(self.team, "inert", {"filters": [], "window_minutes": minutes})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True, strip_inert=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": []}

    def test_refuses_a_row_the_convert_pass_would_still_convert(self) -> None:
        # Stripping here would move the window from two days to the default, which is the one outcome
        # this whole change must not produce. The operator is told to run the convert pass first.
        flow = _flow(self.team, "convertible", {"filters": [], "window_minutes": 2880})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True, strip_inert=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window_minutes": 2880}

    def test_strips_alongside_an_existing_window_without_touching_it(self) -> None:
        flow = _flow(self.team, "both", {"filters": [], "window": "7d", "window_minutes": 60})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True, strip_inert=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window": "7d"}

    @parameterized.expand([("a string the grammar rejects", "1 week"), ("a duration of zero", "0d")])
    def test_refuses_a_row_whose_window_the_matcher_cannot_read(self, _name: str, window: str) -> None:
        # A window the shared grammar cannot parse to a positive value is not a window: the legacy
        # value is what the row measures today, so the convert pass still owns this row.
        flow = _flow(self.team, "unreadable window", {"filters": [], "window": window, "window_minutes": 2880})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True, strip_inert=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window": window, "window_minutes": 2880}

    def test_refuses_a_convertible_draft_snapshot_or_template_and_says_so(self) -> None:
        # A convertible value hiding in a draft, a snapshot or a template is not inert: publishing,
        # restoring or building from it after the field is gone drops the window. Skipping it silently
        # would report a clean sweep.
        flow = _flow(self.team, "clean live row", {"filters": []})
        flow.draft = {"conversion": {"filters": [], "window_minutes": 2880}}
        flow.save()
        with team_scope(self.team.pk):
            revision = HogFlowRevision.objects.create(
                team=self.team,
                hog_flow=flow,
                version=1,
                content={"conversion": {"filters": [], "window_minutes": 1440}},
            )
        template = _template(self.team, {"filters": [], "window_minutes": 60})

        out = StringIO()
        call_command(
            "migrate_conversion_window_to_duration",
            team_id=self.team.pk,
            live_run=True,
            strip_inert=True,
            stdout=out,
        )

        flow.refresh_from_db()
        revision.refresh_from_db()
        template.refresh_from_db()
        assert flow.draft == {"conversion": {"filters": [], "window_minutes": 2880}}
        assert revision.content == {"conversion": {"filters": [], "window_minutes": 1440}}
        assert template.conversion == {"filters": [], "window_minutes": 60}
        assert "3 flow(s), draft(s), snapshot(s) or template(s) still carry a convertible value" in out.getvalue()

    def test_strips_drafts_revision_snapshots_and_templates(self) -> None:
        # A snapshot or a template that keeps the key puts it back the moment someone restores that
        # version or builds a workflow from it.
        flow = _flow(self.team, "with draft", {"filters": [], "window_minutes": 0})
        flow.draft = {"conversion": {"filters": [], "window_minutes": None}}
        flow.save()
        with team_scope(self.team.pk):
            revision = HogFlowRevision.objects.create(
                team=self.team,
                hog_flow=flow,
                version=1,
                content={"conversion": {"filters": [], "window_minutes": 0}},
            )
        template = _template(self.team, {"filters": [], "window_minutes": None})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, live_run=True, strip_inert=True)

        flow.refresh_from_db()
        revision.refresh_from_db()
        template.refresh_from_db()
        assert flow.conversion == {"filters": []}
        assert flow.draft == {"conversion": {"filters": []}}
        assert revision.content == {"conversion": {"filters": []}}
        assert template.conversion == {"filters": []}

    def test_dry_run_writes_nothing(self) -> None:
        flow = _flow(self.team, "inert", {"filters": [], "window_minutes": 0})

        call_command("migrate_conversion_window_to_duration", team_id=self.team.pk, strip_inert=True)

        flow.refresh_from_db()
        assert flow.conversion == {"filters": [], "window_minutes": 0}
