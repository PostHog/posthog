from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import param, parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.database.database import Database

from posthog.models.event.new_events_schema import (
    EVENTS_TABLE_ROLLOUT_FLAG,
    EVENTS_TABLE_SELF_SERVE_FLAG,
    events_route_scope,
    new_events_schema_for_request,
)
from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import (
    FlagEvaluationsConfig,
    events_lack_new_flag_calls,
    get_flag_evaluations_read_config,
    get_organization_flag_evaluations_config,
    is_flag_evaluations_table_enabled,
    reads_flag_calls_from_flag_evaluations,
    reads_flag_calls_without_events_fallback,
)
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig


class TestOrganizationFeatureFlagsConfig(BaseTest):
    @parameterized.expand(
        [
            ("events", 0, FlagEvaluationsMode.EVENTS),
            ("read_flag_evaluations", 1, FlagEvaluationsMode.READ_FLAG_EVALUATIONS),
            ("an_invalid_setting_falls_back_to_events", 7, FlagEvaluationsMode.EVENTS),
        ]
    )
    def test_a_new_organization_takes_the_new_org_mode(self, _name, new_org_mode, expected_mode):
        with self.settings(FLAG_EVALUATIONS_NEW_ORG_MODE=new_org_mode):
            organization = Organization.objects.create(name="New organization")

        self.assertEqual(
            OrganizationFeatureFlagsConfig.objects.get(organization=organization).flag_evaluations_mode, expected_mode
        )

    def test_saving_an_existing_organization_keeps_its_mode(self):
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).update(
            flag_evaluations_mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS
        )

        with self.settings(FLAG_EVALUATIONS_NEW_ORG_MODE=FlagEvaluationsMode.EVENTS):
            self.organization.name = "Renamed"
            self.organization.save()

        self.assertEqual(
            OrganizationFeatureFlagsConfig.objects.get(organization=self.organization).flag_evaluations_mode,
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
        )


class TestFlagEvaluationsTableGate(BaseTest):
    @parameterized.expand(
        [
            param("self_hosted_events", FlagEvaluationsMode.EVENTS, expected=False),
            param("self_hosted_read_flag_evaluations", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, expected=True),
            param("self_hosted_flag_evaluations_only", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, expected=True),
            param("self_hosted_no_config_row", None, expected=False),
            param(
                "self_hosted_read_flag_evaluations_while_reads_are_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                expected=True,
                reads_forced_to_events=True,
            ),
            param("cloud_events", FlagEvaluationsMode.EVENTS, expected=True, cloud=True),
            param("cloud_no_config_row", None, expected=True, cloud=True),
        ]
    )
    def test_table_is_enabled_on_cloud_or_by_the_organization_mode(
        self,
        _name: str,
        mode: FlagEvaluationsMode | None,
        *,
        expected: bool,
        cloud: bool = False,
        reads_forced_to_events: bool = False,
    ) -> None:
        config = OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization)
        if mode is None:
            config.delete()
        else:
            config.update(flag_evaluations_mode=mode)

        with (
            self.settings(DEBUG=False, E2E_TESTING=False),
            self.is_cloud(cloud),
            override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", reads_forced_to_events),
        ):
            self.assertEqual(is_flag_evaluations_table_enabled(self.team), expected)


class TestFlagCallReadersFollowTheEventsTable(BaseTest):
    @parameterized.expand(
        [
            param("legacy_events", FlagEvaluationsMode.EVENTS, reads=False, only=False),
            param("legacy_read", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, reads=True, only=False),
            param(
                "legacy_read_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                reads=False,
                only=False,
                reads_forced_to_events=True,
            ),
            param("legacy_only", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, reads=True, only=True),
            param(
                "legacy_only_that_keeps_events_writes",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                reads=True,
                only=False,
                no_fallback=True,
                keeps_events_writes=True,
            ),
            param(
                "legacy_only_that_keeps_events_writes_forced_to_events",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                reads=False,
                only=False,
                no_fallback=False,
                keeps_events_writes=True,
                reads_forced_to_events=True,
            ),
            param("native_events", FlagEvaluationsMode.EVENTS, reads=True, only=True, native=True),
            param("native_read", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, reads=True, only=True, native=True),
            param(
                "native_read_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                reads=True,
                only=True,
                native=True,
                reads_forced_to_events=True,
            ),
            param(
                "native_query_on_a_legacy_instance",
                FlagEvaluationsMode.EVENTS,
                reads=True,
                only=False,
                query_reads_native=True,
            ),
            param(
                "legacy_query_on_a_native_instance_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                reads=False,
                only=True,
                native=True,
                query_reads_native=False,
                reads_forced_to_events=True,
            ),
            param(
                "native_events_without_the_table",
                FlagEvaluationsMode.EVENTS,
                reads=False,
                only=False,
                native=True,
                cloud=False,
            ),
        ]
    )
    def test_flag_call_readers_pick_flag_evaluations_by_mode_and_events_table(
        self,
        _name: str,
        mode: FlagEvaluationsMode,
        *,
        reads: bool,
        only: bool,
        native: bool = False,
        query_reads_native: bool | None = None,
        cloud: bool = True,
        reads_forced_to_events: bool = False,
        keeps_events_writes: bool = False,
        no_fallback: bool | None = None,
    ) -> None:
        modifiers = HogQLQueryModifiers(useNewEventsSchema=query_reads_native)
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).update(
            flag_evaluations_mode=mode, keep_writing_flag_calls_to_events=keeps_events_writes
        )

        with (
            self.settings(DEBUG=False, E2E_TESTING=False, CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native),
            self.is_cloud(cloud),
            override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", reads_forced_to_events),
        ):
            self.assertEqual(reads_flag_calls_from_flag_evaluations(self.team, modifiers), reads)
            self.assertEqual(events_lack_new_flag_calls(self.team), only)
            self.assertEqual(
                reads_flag_calls_without_events_fallback(self.team), only if no_fallback is None else no_fallback
            )


class TestReadConfigOfAnOrganizationOnTheNewEventsTable(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="Other")

    def _store(self, mode: FlagEvaluationsMode, keeps_events_writes: bool = False) -> None:
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).update(
            flag_evaluations_mode=mode, keep_writing_flag_calls_to_events=keeps_events_writes
        )

    def _listed(self, *teams: Team) -> str:
        return ",".join(str(team.id) for team in teams)

    @parameterized.expand(
        [
            param("events", FlagEvaluationsMode.EVENTS, expected=(FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True)),
            param(
                "read_flag_evaluations",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                expected=(FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True),
            ),
            param(
                "flag_evaluations_only_keeps_its_stopped_writes",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                expected=(FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False),
            ),
            param(
                "one_team_left_on_the_legacy_table",
                FlagEvaluationsMode.EVENTS,
                expected=(FlagEvaluationsMode.EVENTS, False),
                other_team_moved=False,
            ),
            param(
                "an_environment_left_on_the_legacy_table",
                FlagEvaluationsMode.EVENTS,
                expected=(FlagEvaluationsMode.EVENTS, False),
                other_team_moved=False,
                other_is_environment=True,
            ),
            param(
                "forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                expected=(FlagEvaluationsMode.EVENTS, True),
                reads_forced_to_events=True,
            ),
            param(
                "self_hosted_without_the_table",
                FlagEvaluationsMode.EVENTS,
                expected=(FlagEvaluationsMode.EVENTS, False),
                cloud=False,
            ),
            param(
                "self_hosted_with_the_table",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                expected=(FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True),
                cloud=False,
            ),
            param(
                "self_hosted_with_every_project_switched",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                expected=(FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True),
                cloud=False,
                other_team_moved=False,
                every_project_switched=True,
            ),
        ]
    )
    def test_reads_as_mode_2_with_kept_writes_only_when_every_team_reads_the_new_table(
        self,
        _name: str,
        stored_mode: FlagEvaluationsMode,
        *,
        expected: tuple[FlagEvaluationsMode, bool],
        other_team_moved: bool = True,
        other_is_environment: bool = False,
        reads_forced_to_events: bool = False,
        cloud: bool = True,
        every_project_switched: bool = False,
    ) -> None:
        if other_is_environment:
            self.other_team.parent_team = self.team
            self.other_team.project = self.team.project
            self.other_team.save()
        self._store(stored_mode)
        listed = self._listed(self.team, self.other_team) if other_team_moved else self._listed(self.team)

        with (
            self.settings(DEBUG=False, E2E_TESTING=False),
            self.is_cloud(cloud),
            override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", listed),
            override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", every_project_switched),
            override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", reads_forced_to_events),
        ):
            read_config = get_flag_evaluations_read_config(self.organization.id)
            hinted_read_config = get_flag_evaluations_read_config(self.organization.id, team_id=self.team.id)
            stored_config = get_organization_flag_evaluations_config(self.organization.id)

        expected_config = FlagEvaluationsConfig(mode=expected[0], keeps_events_writes=expected[1])
        self.assertEqual(read_config, expected_config)
        self.assertEqual(hinted_read_config, expected_config)
        # Ingestion and experiment health read the stored config, so the move must not change what they see.
        self.assertEqual(stored_config.mode, stored_mode)

    @parameterized.expand(
        [
            param("a_staff_cookie", lambda: new_events_schema_for_request(True), every_team_moved=False),
            param(
                "a_query_route",
                lambda: events_route_scope(HogQLQueryModifiers(useNewEventsSchema=True)),
                every_team_moved=False,
            ),
            param("a_legacy_staff_cookie", lambda: new_events_schema_for_request(False), every_team_moved=True),
            param(
                "a_legacy_query_route",
                lambda: events_route_scope(HogQLQueryModifiers(useNewEventsSchema=False)),
                every_team_moved=True,
            ),
        ]
    )
    def test_a_per_request_override_keeps_the_stored_mode(self, _name, override, *, every_team_moved: bool) -> None:
        listed = self._listed(self.team, self.other_team) if every_team_moved else ""

        with (
            self.is_cloud(True),
            override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", listed),
            override(),
        ):
            self.assertEqual(get_flag_evaluations_read_config(self.organization.id).mode, FlagEvaluationsMode.EVENTS)

    def test_a_legacy_query_on_a_moved_organization_reads_the_events_copy(self) -> None:
        legacy = HogQLQueryModifiers(useNewEventsSchema=False)

        with (
            self.is_cloud(True),
            override_instance_config(
                "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", self._listed(self.team, self.other_team)
            ),
        ):
            database = Database.create_for(team=self.team, modifiers=legacy)
            reads_flag_evaluations = reads_flag_calls_from_flag_evaluations(self.team, legacy)
            native_reads_flag_evaluations_only = reads_flag_calls_without_events_fallback(self.team)

        self.assertFalse(database.organization_reads_flag_calls_from_flag_evaluations)
        self.assertFalse(reads_flag_evaluations)
        self.assertTrue(native_reads_flag_evaluations_only)

    @parameterized.expand(
        [
            param("rollout_flag", {EVENTS_TABLE_ROLLOUT_FLAG}, expected=FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY),
            param("flag_definitions_not_loaded", set(), expected=FlagEvaluationsMode.EVENTS),
            param("project_opt_in_alone", {EVENTS_TABLE_SELF_SERVE_FLAG}, expected=FlagEvaluationsMode.EVENTS),
        ]
    )
    def test_the_rollout_flag_moves_the_organization_and_the_opt_in_does_not(
        self, _name: str, flags_on: set[str], *, expected: FlagEvaluationsMode
    ) -> None:
        Team.objects.filter(organization=self.organization).update(modifiers={"useNewEventsSchema": True})

        def feature_enabled(flag: str, *args, **kwargs) -> bool | None:
            return True if flag in flags_on else None

        with (
            self.is_cloud(True),
            patch("posthog.models.event.new_events_schema.posthoganalytics.feature_enabled", feature_enabled),
        ):
            self.assertEqual(get_flag_evaluations_read_config(self.organization.id).mode, expected)

    def test_an_organization_without_teams_keeps_its_stored_mode(self) -> None:
        organization = Organization.objects.create(name="No teams")

        with self.is_cloud(True), override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", True):
            self.assertEqual(get_flag_evaluations_read_config(organization.id).mode, FlagEvaluationsMode.EVENTS)

    @parameterized.expand(
        [
            param("no_project_can_move", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, cloud=False, hint=False),
            param("the_hinted_team_has_not_moved", FlagEvaluationsMode.EVENTS, cloud=True, hint=True),
        ]
    )
    def test_reads_no_team_rows_when_the_organization_cannot_have_moved(
        self, _name: str, stored_mode: FlagEvaluationsMode, *, cloud: bool, hint: bool
    ) -> None:
        self._store(stored_mode)
        listed = self._listed(self.other_team) if cloud else ""

        with (
            self.settings(DEBUG=False, E2E_TESTING=False),
            self.is_cloud(cloud),
            override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", listed),
            override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", False),
        ):
            # The first read fills the instance setting cache.
            get_flag_evaluations_read_config(self.organization.id)
            with self.assertNumQueries(1):
                read_config = get_flag_evaluations_read_config(
                    self.organization.id, team_id=self.team.id if hint else None
                )

        self.assertEqual(read_config.mode, stored_mode)
