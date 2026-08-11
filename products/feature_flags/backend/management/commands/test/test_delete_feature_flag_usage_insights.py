import tempfile
from io import StringIO
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.helpers.dashboard_templates import (
    FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME,
    add_enriched_insights_to_feature_flag_dashboard,
)
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team import Team
from posthog.test.persons import create_group_type_mapping

from products.alerts.backend.models.alert import AlertConfiguration
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.feature_flags.backend.api.feature_flag import _create_usage_dashboard
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_analytics.backend.models.insight import Insight


class TestDeleteFeatureFlagUsageInsights(BaseTest):
    def _flag_with_usage_dashboard(
        self,
        key: str,
        enriched: bool = False,
        aggregation_group_type_index: int | None = None,
        team: Team | None = None,
    ) -> FeatureFlag:
        team = team or self.team
        filters: dict[str, Any] = {"groups": [{"rollout_percentage": 100}]}
        if aggregation_group_type_index is not None:
            create_group_type_mapping(
                team=team,
                project_id=team.project_id,
                group_type="organization",
                group_type_index=aggregation_group_type_index,
            )
            # `FeatureFlag.aggregation_group_type_index` reads through to filters.
            filters["aggregation_group_type_index"] = aggregation_group_type_index
        flag = FeatureFlag.objects.create(team=team, created_by=self.user, key=key, filters=filters)
        # Built through the API's own helper so the dashboard is shaped the way production shapes it.
        dashboard = _create_usage_dashboard(flag, self.user)
        if enriched:
            add_enriched_insights_to_feature_flag_dashboard(flag, dashboard)
        return flag

    def _usage_insights(self, flag: FeatureFlag) -> list[Insight]:
        assert flag.usage_dashboard_id is not None
        tile_insight_ids = DashboardTile.objects.filter(dashboard_id=flag.usage_dashboard_id).values_list(
            "insight_id", flat=True
        )
        return list(Insight.objects_including_soft_deleted.filter(id__in=tile_insight_ids).order_by("id"))

    @parameterized.expand(
        [
            ("user_aggregation", None, FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME),
            ("group_aggregation", 0, "Feature Flag calls made by unique organizations per variant"),
        ]
    )
    def test_deletes_all_four_generated_insights_and_nulls_usage_dashboard(
        self, key: str, aggregation_group_type_index: int | None, expected_unique_calls_name: str
    ) -> None:
        # All four generated insights must come off the dashboard, so the flag ends up unlinked.
        # The group case pins the pluralized unique-calls name the generator produces; its description
        # matches the classifier's description arm too, so this does not isolate the name arms.
        flag = self._flag_with_usage_dashboard(
            key, enriched=True, aggregation_group_type_index=aggregation_group_type_index
        )
        dashboard_id = flag.usage_dashboard_id
        assert dashboard_id is not None
        insights = self._usage_insights(flag)
        assert len(insights) == 4
        assert expected_unique_calls_name in {i.name for i in insights}

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0")

        assert Insight.objects.filter(id__in=[i.id for i in insights]).count() == 0
        assert DashboardTile.objects.filter(dashboard_id=dashboard_id).count() == 0
        flag.refresh_from_db()
        assert flag.usage_dashboard_id is None
        # Activity is system-attributed since there is no request user.
        logged = ActivityLog.objects.filter(scope="Insight", activity="deleted", item_id=str(insights[0].id)).first()
        assert logged is not None
        assert logged.is_system is True

    def test_matches_generated_names_when_descriptions_have_drifted(self) -> None:
        # The name arms are the classifier's only reach once description wording changes, and the
        # descriptions are prose that a copy edit can reword. Clearing them isolates the name arms.
        flag = self._flag_with_usage_dashboard("drifted")
        insights = self._usage_insights(flag)
        Insight.objects.filter(id__in=[i.id for i in insights]).update(description="")

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0")

        assert Insight.objects.filter(id__in=[i.id for i in insights]).count() == 0

    def test_orphaned_insights_are_swept_only_with_the_opt_in(self) -> None:
        # Guards the opt-in gate in both directions: a default run must leave orphans alone, and
        # --include-orphaned must actually delete them.
        flag = self._flag_with_usage_dashboard("orphan")
        insights = self._usage_insights(flag)
        FeatureFlag.objects.filter(id=flag.id).update(usage_dashboard=None)

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0")
        assert Insight.objects.filter(id__in=[i.id for i in insights]).count() == len(insights)

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0", "--include-orphaned")
        assert Insight.objects.filter(id__in=[i.id for i in insights]).count() == 0

    def test_limit_caps_how_many_are_deleted(self) -> None:
        # --limit is the operator's brake, and the truncation is hand-rolled arithmetic against a
        # running total, so an off-by-one here means a capped run deletes everything.
        flag = self._flag_with_usage_dashboard("capped")
        insights = self._usage_insights(flag)

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0", "--limit=1")

        assert Insight.objects.filter(id__in=[i.id for i in insights]).count() == len(insights) - 1

    def test_team_id_confines_the_sweep_to_one_team(self) -> None:
        # Losing this filter turns an operator's single-team run into a fleet-wide one.
        other_team = Team.objects.create(organization=self.organization, name="other")
        mine = self._usage_insights(self._flag_with_usage_dashboard("mine"))
        theirs = self._usage_insights(self._flag_with_usage_dashboard("theirs", team=other_team))

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0", f"--team-id={self.team.id}")

        assert Insight.objects.filter(id__in=[i.id for i in mine]).count() == 0
        assert Insight.objects.filter(id__in=[i.id for i in theirs]).count() == len(theirs)

    def test_leaves_flag_linked_when_its_dashboard_was_already_empty(self) -> None:
        # Only dashboards this run empties should be unlinked. A dashboard that was already tile-less
        # (the user cleared it, or it is in the trash) is not this command's to sever.
        flag = self._flag_with_usage_dashboard("already-empty")
        assert flag.usage_dashboard_id is not None
        DashboardTile.objects_including_soft_deleted.filter(dashboard_id=flag.usage_dashboard_id).delete()

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0")

        flag.refresh_from_db()
        assert flag.usage_dashboard_id is not None

    @parameterized.expand(
        [
            ("missing_file", "/nonexistent/keep.txt", None),
            ("nothing_parseable", None, "insight_id\nnot-an-id\n"),
        ]
    )
    def test_unusable_keep_list_stops_the_run(self, _name: str, path: str | None, contents: str | None) -> None:
        # The keep-list is the only thing protecting in-use insights, so it must fail closed rather
        # than sweep with an empty one.
        if contents is not None:
            keep_file = Path(self.enterContext(tempfile.TemporaryDirectory())) / "keep.txt"
            keep_file.write_text(contents)
            path = str(keep_file)

        with self.assertRaises(CommandError):
            call_command("delete_feature_flag_usage_insights", "--sleep-interval=0", f"--keep-ids-file={path}")

    def test_does_not_delete_unrelated_sample_insight(self) -> None:
        # The classifier keys on name/description, not is_sample — so other dashboard-template insights
        # (billing, onboarding) that also carry is_sample must survive.
        unrelated = Insight.objects.create(
            team=self.team, name="Billable Event Usage by Library", is_sample=True, saved=True
        )

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0", "--include-orphaned")

        assert Insight.objects.filter(id=unrelated.id).exists()

    @parameterized.expand(["favorited", "edited", "sharing", "alert", "keep_list"])
    def test_keeps_insight_with_usage_signal_and_leaves_dashboard_linked(self, signal: str) -> None:
        flag = self._flag_with_usage_dashboard(f"flag-{signal}")
        insights = self._usage_insights(flag)
        kept, other = insights[0], insights[1]

        extra_args: list[str] = []
        if signal == "favorited":
            kept.favorited = True
            kept.save()
        elif signal == "edited":
            # What the insight API leaves behind on any PATCH, so it stands in for a user edit.
            kept.is_sample = False
            kept.save()
        elif signal == "sharing":
            SharingConfiguration.objects.create(team=self.team, insight=kept, enabled=True)
        elif signal == "alert":
            AlertConfiguration.objects.create(team=self.team, insight=kept, created_by=self.user, name="a")
        elif signal == "keep_list":
            keep_file = Path(self.enterContext(tempfile.TemporaryDirectory())) / "keep.txt"
            keep_file.write_text(f"insight_id\n{kept.id}\n")
            extra_args = [f"--keep-ids-file={keep_file}"]

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0", *extra_args)

        assert Insight.objects.filter(id=kept.id).exists()
        assert not Insight.objects.filter(id=other.id).exists()
        # A kept insight still lives on the dashboard, so the flag must stay linked to it.
        flag.refresh_from_db()
        assert flag.usage_dashboard_id is not None

    def test_dry_run_changes_nothing_but_reports_the_flags_it_would_unlink(self) -> None:
        # A dry run sizes the live run, so it has to account for both mutations. Reporting the
        # deletes while silently reporting zero unlinks would understate what the live run does.
        flag = self._flag_with_usage_dashboard("dry")
        insights = self._usage_insights(flag)
        out = StringIO()

        call_command("delete_feature_flag_usage_insights", "--sleep-interval=0", "--dry-run", stdout=out)

        assert Insight.objects.filter(id__in=[i.id for i in insights]).count() == len(insights)
        flag.refresh_from_db()
        assert flag.usage_dashboard_id is not None
        assert "nulled 1 flag usage_dashboard references" in out.getvalue()
