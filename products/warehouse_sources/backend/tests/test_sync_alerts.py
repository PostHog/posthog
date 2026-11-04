from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.alerts.backend.facade.destinations import MAX_DESTINATIONS_PER_ALERT
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import (
    create_configuration,
    delete_configuration,
    list_alert_destinations,
    list_configurations,
    record_outcomes,
    slot_of,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    Grouping,
    GroupingMode,
    IncidentAction,
    PlatformAlertConfigurationEdit,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
    SourceKind,
)
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.presentation.views import warehouse_alert_destinations as destinations_view
from products.warehouse_sources.backend.sync_alerts.destinations import EVENT_IDS_BY_KIND
from products.warehouse_sources.backend.sync_alerts.email_recipients import project_member_emails
from products.warehouse_sources.backend.sync_alerts.evaluation import evaluate_warehouse_alert_batch
from products.warehouse_sources.backend.sync_alerts.wording import (
    describe_destination_transition,
    describe_source_transition,
)

Status = ExternalDataSchema.Status
DestinationStatus = ExternalDataDestination.Status
SECRET = "hunter2-correct-horse"
PAGERDUTY_ROUTING_KEY = "0123456789abcdef0123456789abcdef"


class TestWarehouseAlerts(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = timezone.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True))

    def _source(self, team: Team | None = None, prefix: str | None = None, **fields: Any) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=team or self.team,
            source_id="src",
            connection_id="conn",
            status="Running",
            source_type="Postgres",
            prefix=prefix,
            **fields,
        )

    def _schema(self, source: ExternalDataSource, name: str, status_: str, **fields: Any) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team=self.team, source=source, name=name, status=status_, latest_error=f"{name} broke", **fields
        )

    def _destination(self, name: str, status_: str, team: Team | None = None, **fields: Any) -> ExternalDataDestination:
        team_id = (team or self.team).pk
        return ExternalDataDestination.objects.for_team(team_id).create(
            team_id=team_id, type=ExternalDataDestination.Type.SNOWFLAKE, name=name, status=status_, **fields
        )

    def _alert(
        self,
        kind: SourceKind,
        source_config: dict[str, Any],
        grouping_key: str,
        schedule_restriction: dict[str, Any] | None = None,
    ) -> UUID:
        with team_scope(self.team.id):
            view = create_configuration(
                team_id=self.team.id,
                source_kind=kind,
                edit=PlatformAlertConfigurationEdit(
                    name="Sync failures",
                    enabled=True,
                    source_config=source_config,
                    grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=(grouping_key,)),
                    schedule_restriction=schedule_restriction,
                    evaluation_periods=1,
                    datapoints_to_alarm=1,
                    cooldown_minutes=0,
                ),
                created_by_id=self.user.id,
            )
            platform_testing.set_due_at(view.id, self.cutoff - timedelta(minutes=1))
        return view.id

    def _evaluate(self, kind: SourceKind) -> SourceBatchEvaluation:
        with team_scope(self.team.id):
            return evaluate_warehouse_alert_batch(
                kind, self.team.id, slot_of(self.cutoff - timedelta(minutes=1), self.cutoff), self.cutoff
            )

    def _only_outcome(self, evaluation: SourceBatchEvaluation) -> PlatformAlertOutcome:
        (outcome,) = evaluation.outcomes
        return outcome

    def _next_check(self, configuration_id: UUID, outcome: PlatformAlertOutcome) -> None:
        with team_scope(self.team.id):
            record_outcomes(self.team.id, [outcome], self.cutoff)
            self.cutoff += timedelta(minutes=5)
            platform_testing.set_due_at(configuration_id, self.cutoff - timedelta(minutes=1))

    def _add_pagerduty(self, configuration_id: UUID) -> str:
        added = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_alerts/{configuration_id}/destinations/",
            {"type": "pagerduty", "pagerduty_routing_key": PAGERDUTY_ROUTING_KEY},
            format="json",
        )
        assert added.status_code == status.HTTP_201_CREATED, added.json()
        return added.json()["id"]

    def _create_on_the_platform(self, body: dict[str, Any]) -> Any:
        return self.client.post(f"/api/projects/{self.team.id}/platform_alerts/", body, format="json")

    @parameterized.expand(
        [
            ("every_source_by_table", {"group_by": "schema"}, "schema_id", {"a_failed", "a_halted", "b_failed"}),
            (
                "billing_limits_included",
                {"group_by": "schema", "include_billing_limits": True},
                "schema_id",
                {"a_failed", "a_halted", "a_billing", "b_failed"},
            ),
            ("one_source_in_scope", {"group_by": "schema", "source_ids": ["a"]}, "schema_id", {"a_failed", "a_halted"}),
            ("grouped_by_source", {"group_by": "source"}, "source_id", {"a", "b"}),
        ]
    )
    def test_a_source_check_fires_for_each_failing_group_in_scope(
        self, _name: str, source_config: dict[str, Any], grouping_key: str, expected: set[str]
    ) -> None:
        sources = {"a": self._source(prefix="prod"), "b": self._source()}
        ids = {name: str(source.id) for name, source in sources.items()}
        schemas: list[tuple[str, str, str, dict[str, Any]]] = [
            ("a_failed", "a", Status.FAILED, {}),
            ("a_completed", "a", Status.COMPLETED, {}),
            ("a_billing", "a", Status.BILLING_LIMIT_REACHED, {}),
            ("a_deleted", "a", Status.FAILED, {"deleted": True}),
            ("a_turned_off", "a", Status.FAILED, {"should_sync": False}),
            ("a_halted", "a", Status.FAILED, {"should_sync": False, "auto_disabled_at": timezone.now()}),
            ("b_failed", "b", Status.FAILED, {}),
        ]
        for name, source_name, status_, fields in schemas:
            ids[name] = str(self._schema(sources[source_name], name, status_, **fields).id)
        self._source(team=Team.objects.create(organization=self.organization), prefix="other")
        if "source_ids" in source_config:
            source_config = {**source_config, "source_ids": [ids[name] for name in source_config["source_ids"]]}

        self._alert(SourceKind.WAREHOUSE_SOURCE, source_config, grouping_key)
        evaluation = self._evaluate(SourceKind.WAREHOUSE_SOURCE)

        outcome = self._only_outcome(evaluation)
        assert {group.grouping_key: group.kind for group in outcome.groups} == {
            ids[name]: AlertEventKind.FIRING for name in expected
        }
        if grouping_key == "source_id":
            assert {group.grouping_key: group.value for group in outcome.groups} == {ids["a"]: 2.0, ids["b"]: 1.0}
        (delivery,) = evaluation.deliveries
        assert (delivery.sends_messages, delivery.owned_by_platform, delivery.event_ids_by_kind) == (
            True,
            True,
            {"firing": "$warehouse_source_alert_firing", "resolved": "$warehouse_source_alert_resolved"},
        )

    @parameterized.expand(
        [
            ("synced_again", {"status": Status.COMPLETED}),
            ("deleted", {"deleted": True}),
            ("turned_off", {"should_sync": False}),
        ]
    )
    def test_a_table_that_stops_failing_resolves_and_the_resolve_names_it(
        self, _name: str, change: dict[str, Any]
    ) -> None:
        schema = self._schema(self._source(prefix="prod"), "charges", Status.FAILED)
        configuration_id = self._alert(SourceKind.WAREHOUSE_SOURCE, {"group_by": "schema"}, "schema_id")
        self._next_check(configuration_id, self._only_outcome(self._evaluate(SourceKind.WAREHOUSE_SOURCE)))
        ExternalDataSchema.objects.filter(id=schema.id).update(**change)

        evaluation = self._evaluate(SourceKind.WAREHOUSE_SOURCE)

        (group,) = self._only_outcome(evaluation).groups
        assert (group.grouping_key, group.kind, group.labels["schema"], group.labels["source"]) == (
            str(schema.id),
            AlertEventKind.RESOLVED,
            "charges",
            "Postgres (prod)",
        )
        (delivery,) = evaluation.deliveries
        assert delivery.sends_messages

    def test_a_table_that_keeps_failing_announces_once(self) -> None:
        self._schema(self._source(), "charges", Status.FAILED)
        configuration_id = self._alert(SourceKind.WAREHOUSE_SOURCE, {"group_by": "schema"}, "schema_id")
        self._next_check(configuration_id, self._only_outcome(self._evaluate(SourceKind.WAREHOUSE_SOURCE)))

        evaluation = self._evaluate(SourceKind.WAREHOUSE_SOURCE)

        (group,) = self._only_outcome(evaluation).groups
        assert (group.kind, group.new_state, evaluation.deliveries) == (AlertEventKind.CHECK, "firing", ())

    def test_a_billing_limit_resolution_keeps_labels_when_another_check_includes_limits(self) -> None:
        schema = self._schema(self._source(prefix="prod"), "charges", Status.FAILED)
        excluding_id = self._alert(SourceKind.WAREHOUSE_SOURCE, {"group_by": "schema"}, "schema_id")
        including_id = self._alert(
            SourceKind.WAREHOUSE_SOURCE,
            {"group_by": "schema", "include_billing_limits": True},
            "schema_id",
        )
        initial = self._evaluate(SourceKind.WAREHOUSE_SOURCE)
        with team_scope(self.team.id):
            record_outcomes(self.team.id, initial.outcomes, self.cutoff)
            self.cutoff += timedelta(minutes=5)
            for configuration_id in (excluding_id, including_id):
                platform_testing.set_due_at(configuration_id, self.cutoff - timedelta(minutes=1))
        ExternalDataSchema.objects.filter(id=schema.id).update(status=Status.BILLING_LIMIT_REACHED)

        outcomes = {
            outcome.configuration_id: outcome for outcome in self._evaluate(SourceKind.WAREHOUSE_SOURCE).outcomes
        }

        (resolved,) = outcomes[excluding_id].groups
        assert (resolved.kind, resolved.labels["schema"], resolved.labels["source"]) == (
            AlertEventKind.RESOLVED,
            "charges",
            "Postgres (prod)",
        )
        (still_firing,) = outcomes[including_id].groups
        assert still_firing.kind == AlertEventKind.CHECK

    @parameterized.expand([("by_table", "schema", "schema_id"), ("by_source", "source", "source_id")])
    def test_a_failed_table_that_retries_stays_open_until_the_retry_ends(
        self, _name: str, group_by: str, grouping_key: str
    ) -> None:
        schema = self._schema(self._source(), "charges", Status.FAILED)
        configuration_id = self._alert(SourceKind.WAREHOUSE_SOURCE, {"group_by": group_by}, grouping_key)
        self._next_check(configuration_id, self._only_outcome(self._evaluate(SourceKind.WAREHOUSE_SOURCE)))
        ExternalDataSchema.objects.filter(id=schema.id).update(status=Status.RUNNING)

        retrying = self._evaluate(SourceKind.WAREHOUSE_SOURCE)

        assert [group.kind for group in self._only_outcome(retrying).groups] == []
        assert retrying.deliveries == ()
        self._next_check(configuration_id, self._only_outcome(retrying))
        ExternalDataSchema.objects.filter(id=schema.id).update(status=Status.COMPLETED)

        (group,) = self._only_outcome(self._evaluate(SourceKind.WAREHOUSE_SOURCE)).groups
        assert group.kind == AlertEventKind.RESOLVED

    def test_a_scoped_check_sees_its_source_past_the_row_limit(self) -> None:
        crowded, watched = self._source(), self._source()
        for name in ("a", "b", "c"):
            self._schema(crowded, name, Status.FAILED)
        schema = self._schema(watched, "charges", Status.FAILED)
        self._alert(SourceKind.WAREHOUSE_SOURCE, {"group_by": "schema", "source_ids": [str(watched.id)]}, "schema_id")

        with patch("products.warehouse_sources.backend.sync_alerts.evaluation.MAX_FAILING_ROWS", 1):
            (group,) = self._only_outcome(self._evaluate(SourceKind.WAREHOUSE_SOURCE)).groups

        assert (group.grouping_key, group.kind) == (str(schema.id), AlertEventKind.FIRING)

    def test_the_error_a_message_quotes_hides_the_source_credentials(self) -> None:
        source = self._source(job_inputs={"host": "db.example.com", "password": SECRET})
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="charges",
            status=Status.FAILED,
            latest_error=f"could not connect with password {SECRET}",
        )
        self._alert(SourceKind.WAREHOUSE_SOURCE, {"group_by": "schema"}, "schema_id")

        (group,) = self._only_outcome(self._evaluate(SourceKind.WAREHOUSE_SOURCE)).groups

        assert group.labels["reason"] == "could not connect with password ***"

    @parameterized.expand(
        [
            ("every_destination", [], {"failing", "paused"}),
            ("one_in_scope", ["paused"], {"paused"}),
        ]
    )
    def test_a_destination_check_fires_for_each_failing_destination_in_scope(
        self, _name: str, scope: list[str], expected: set[str]
    ) -> None:
        destinations = {
            "failing": self._destination("Snowflake prod", DestinationStatus.FAILING, latest_error="Wrong password"),
            "paused": self._destination("Snowflake dev", DestinationStatus.PAUSED),
            "healthy": self._destination("Snowflake eu", DestinationStatus.HEALTHY),
            "deleted": self._destination("Snowflake old", DestinationStatus.FAILING, deleted=True),
        }
        self._alert(
            SourceKind.WAREHOUSE_DESTINATION,
            {"destination_ids": [str(destinations[name].id) for name in scope]},
            "destination_id",
        )

        outcome = self._only_outcome(self._evaluate(SourceKind.WAREHOUSE_DESTINATION))

        assert {group.grouping_key: group.kind for group in outcome.groups} == {
            str(destinations[name].id): AlertEventKind.FIRING for name in expected
        }
        if "failing" in expected:
            failing = next(group for group in outcome.groups if group.grouping_key == str(destinations["failing"].id))
            assert failing.labels == {
                "destination": "Snowflake prod",
                "destination_type": "Snowflake",
                "status": "Failing",
                "reason": "Wrong password",
            }

    @parameterized.expand(
        [
            (
                "grouping_does_not_match_group_by",
                {
                    "source_config": {"group_by": "schema"},
                    "grouping": {"mode": "by_result_labels", "keys": ["source_id"]},
                },
                "grouping",
            ),
            ("default_single_grouping", {"source_config": {"group_by": "source"}}, "grouping"),
            (
                "more_than_one_evaluation_period",
                {
                    "source_config": {"group_by": "source"},
                    "grouping": {"mode": "by_result_labels", "keys": ["source_id"]},
                    "evaluation_periods": 2,
                },
                "evaluation_periods",
            ),
            (
                "source_of_another_project",
                {
                    "source_config": {"group_by": "source", "source_ids": ["other"]},
                    "grouping": {"mode": "by_result_labels", "keys": ["source_id"]},
                },
                "source_config",
            ),
        ]
    )
    def test_a_refused_create_writes_nothing(self, _name: str, body: dict[str, Any], field: str) -> None:
        other = self._source(team=Team.objects.create(organization=self.organization))
        if body["source_config"].get("source_ids"):
            body = {**body, "source_config": {**body["source_config"], "source_ids": [str(other.id)]}}

        response = self._create_on_the_platform({"source_kind": "warehouse_source", **body})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == field
        with team_scope(self.team.id):
            assert (
                list_configurations(
                    team_id=self.team.id, source_kinds=[SourceKind.WAREHOUSE_SOURCE.value], limit=10, offset=0
                ).total
                == 0
            )

    def test_an_edit_naming_a_destination_of_another_project_changes_nothing(self) -> None:
        other = self._destination(
            "Snowflake", DestinationStatus.HEALTHY, team=Team.objects.create(organization=self.organization)
        )
        configuration_id = self._alert(SourceKind.WAREHOUSE_DESTINATION, {}, "destination_id")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/platform_alerts/{configuration_id}/",
            {"source_kind": "warehouse_destination", "source_config": {"destination_ids": [str(other.id)]}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        read = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{configuration_id}/").json()
        assert read["source_config"] == {}

    @parameterized.expand(
        [
            ("alert_only", ["alert:read"], status.HTTP_403_FORBIDDEN),
            ("warehouse_only", ["external_data_source:read"], status.HTTP_403_FORBIDDEN),
            ("alert_and_warehouse", ["alert:read", "external_data_source:read"], status.HTTP_200_OK),
        ]
    )
    def test_reading_destinations_needs_both_alert_and_warehouse_scopes(
        self, _name: str, scopes: list[str], expected: int
    ) -> None:
        configuration_id = self._alert(SourceKind.WAREHOUSE_SOURCE, {}, "source_id")
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(scopes)}")

        response = self.client.get(f"/api/projects/{self.team.id}/warehouse_alerts/{configuration_id}/destinations/")

        assert response.status_code == expected, response.json()

    def test_an_alert_and_its_slack_destination_route_a_failure_to_that_channel(self) -> None:
        schema = self._schema(self._source(), "charges", Status.FAILED)

        created = self._create_on_the_platform(
            {
                "source_kind": "warehouse_source",
                "name": "Sync failures",
                "source_config": {"group_by": "schema"},
                "grouping": {"mode": "by_result_labels", "keys": ["schema_id"]},
            }
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        alert = created.json()
        assert self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{alert['id']}/").json() == alert
        assert alert["owner"] == "platform"

        destinations_url = f"/api/projects/{self.team.id}/warehouse_alerts/{alert['id']}/destinations/"
        added = self.client.post(
            destinations_url,
            {
                "type": "slack",
                "slack_workspace_id": 42,
                "slack_channel_id": "C123",
                "slack_channel_name": "data",
                "pagerduty_routing_key": PAGERDUTY_ROUTING_KEY,
            },
            format="json",
        )
        assert added.status_code == status.HTTP_201_CREATED, added.json()
        (listed,) = self.client.get(destinations_url).json()
        assert listed == added.json()
        # A Slack row keeps no PagerDuty setting, neither the defaults nor a key sent alongside.
        assert not {key for key in listed if key.startswith("pagerduty_")}
        assert (listed["type"], listed["slack_channel_id"], listed["event_kinds"]) == (
            "slack",
            "C123",
            ["firing", "resolved"],
        )

        with team_scope(self.team.id):
            platform_testing.set_due_at(UUID(alert["id"]), self.cutoff - timedelta(minutes=1))
        evaluation = self._evaluate(SourceKind.WAREHOUSE_SOURCE)

        (group,) = self._only_outcome(evaluation).groups
        assert (group.grouping_key, group.kind) == (str(schema.id), AlertEventKind.FIRING)
        (delivery,) = evaluation.deliveries
        assert delivery.destination_alert_id == alert["id"]
        firing_event_id = delivery.event_ids_by_kind[AlertEventKind.FIRING.value]
        assert firing_event_id == EVENT_IDS_BY_KIND[SourceKind.WAREHOUSE_SOURCE]["firing"]

        deleted = self.client.delete(f"/api/projects/{self.team.id}/platform_alerts/{alert['id']}/")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert list_alert_destinations(team_id=self.team.id, configuration_id=UUID(alert["id"])) == ()

    def test_deleting_a_destination_refuses_an_id_of_another_alert(self) -> None:
        mine = self._alert(SourceKind.WAREHOUSE_SOURCE, {}, "source_id")
        other = self._alert(SourceKind.WAREHOUSE_SOURCE, {}, "source_id")
        kept, theirs = self._add_pagerduty(mine), self._add_pagerduty(other)
        delete_url = f"/api/projects/{self.team.id}/warehouse_alerts/{mine}/destinations/delete/"

        refused = self.client.post(delete_url, {"destination_ids": [kept, theirs]}, format="json")
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.json()
        assert [len(list_alert_destinations(team_id=self.team.id, configuration_id=id_)) for id_ in (mine, other)] == [
            1,
            1,
        ]

        assert self.client.post(delete_url, {"destination_ids": [kept]}, format="json").status_code == 204
        assert list_alert_destinations(team_id=self.team.id, configuration_id=mine) == ()

    @parameterized.expand(
        [
            ("announced", None, True),
            ("quiet_hours", {"blocked_windows": [{"start": "11:00", "end": "13:00"}]}, False),
        ]
    )
    def test_a_pagerduty_incident_follows_the_failure_even_when_quiet_hours_hold_the_message(
        self, _name: str, schedule_restriction: dict[str, Any] | None, announced: bool
    ) -> None:
        self.cutoff = self.cutoff.replace(hour=12, minute=0)
        schema = self._schema(self._source(), "charges", Status.FAILED)
        configuration_id = self._alert(
            SourceKind.WAREHOUSE_SOURCE, {"group_by": "schema"}, "schema_id", schedule_restriction
        )
        self._add_pagerduty(configuration_id)

        firing = self._evaluate(SourceKind.WAREHOUSE_SOURCE)
        (fired,) = firing.deliveries
        self._next_check(configuration_id, self._only_outcome(firing))
        ExternalDataSchema.objects.filter(id=schema.id).update(status=Status.COMPLETED)
        (resolved,) = self._evaluate(SourceKind.WAREHOUSE_SOURCE).deliveries

        assert [(delivery.incident_actions, delivery.sends_messages) for delivery in (fired, resolved)] == [
            ({str(schema.id): IncidentAction.TRIGGER}, announced),
            ({str(schema.id): IncidentAction.RESOLVE}, announced),
        ]

    def test_deleting_a_firing_alert_resolves_its_incident_before_the_destination_goes(self) -> None:
        schema = self._schema(self._source(), "charges", Status.FAILED)
        configuration_id = self._alert(SourceKind.WAREHOUSE_SOURCE, {"group_by": "schema"}, "schema_id")
        self._add_pagerduty(configuration_id)
        self._next_check(configuration_id, self._only_outcome(self._evaluate(SourceKind.WAREHOUSE_SOURCE)))
        sent: list[tuple[str, dict[str, IncidentAction], int]] = []

        def deliver(request: Any) -> None:
            live = len(list_alert_destinations(team_id=self.team.id, configuration_id=configuration_id))
            sent.append((request.destination_alert_id, request.incident_actions, live))

        with patch("products.alerts_platform.backend.temporal.web_start.deliver_evaluation", side_effect=deliver):
            deleted = self.client.delete(f"/api/projects/{self.team.id}/platform_alerts/{configuration_id}/")

        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert sent == [(str(configuration_id), {str(schema.id): IncidentAction.RESOLVE}, 1)]
        assert list_alert_destinations(team_id=self.team.id, configuration_id=configuration_id) == ()

    def test_an_alert_takes_only_a_few_destinations(self) -> None:
        configuration_id = self._alert(SourceKind.WAREHOUSE_SOURCE, {}, "source_id")
        destinations_url = f"/api/projects/{self.team.id}/warehouse_alerts/{configuration_id}/destinations/"

        def add(channel: str) -> Any:
            return self.client.post(
                destinations_url,
                {"type": "slack", "slack_workspace_id": 42, "slack_channel_id": channel},
                format="json",
            )

        for index in range(MAX_DESTINATIONS_PER_ALERT):
            assert add(f"C{index}").status_code == status.HTTP_201_CREATED

        refused = add("C-one-too-many")

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.json()
        assert len(self.client.get(destinations_url).json()) == MAX_DESTINATIONS_PER_ALERT

    def test_a_destination_added_while_its_alert_is_deleted_is_refused(self) -> None:
        configuration_id = self._alert(SourceKind.WAREHOUSE_SOURCE, {}, "source_id")
        real_get_configuration = destinations_view.get_configuration

        def deleted_in_between(**kwargs: Any) -> Any:
            # The alert goes after the request has read it, before its destinations are inserted.
            if kwargs.get("lock"):
                delete_configuration(
                    team_id=self.team.id,
                    source_kinds=[SourceKind.WAREHOUSE_SOURCE.value],
                    configuration_id=configuration_id,
                )
            return real_get_configuration(**kwargs)

        with patch.object(destinations_view, "get_configuration", side_effect=deleted_in_between):
            response = self.client.post(
                f"/api/projects/{self.team.id}/warehouse_alerts/{configuration_id}/destinations/",
                {"type": "slack", "slack_workspace_id": 42, "slack_channel_id": "C1"},
                format="json",
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
        assert list_alert_destinations(team_id=self.team.id, configuration_id=configuration_id) == ()

    @parameterized.expand(
        [
            (
                "table",
                SourceKind.WAREHOUSE_SOURCE,
                "schema-1",
                {"group_by": "schema"},
                {"source_id": "source-1", "source": "Stripe", "schema": "charges", "reason": "Bad key"},
                [("Source", "Stripe"), ("Table", "charges"), ("Error", "Bad key")],
                "/project/7/data-management/sources/managed-source-1/syncs",
            ),
            (
                "source",
                SourceKind.WAREHOUSE_SOURCE,
                "source-1",
                {"group_by": "source"},
                {"source_id": "source-1", "source": "Stripe", "schema": "charges, refunds"},
                [("Source", "Stripe"), ("Failing tables", "charges, refunds")],
                "/project/7/data-management/sources/managed-source-1/syncs",
            ),
            (
                "destination",
                SourceKind.WAREHOUSE_DESTINATION,
                "destination-1",
                {},
                {"destination": "Snowflake prod", "destination_type": "Snowflake", "status": "Paused"},
                [("Destination", "Snowflake prod"), ("Type", "Snowflake"), ("Status", "Paused")],
                "/project/7/data-management/warehouse-destinations?destination=destination-1",
            ),
        ]
    )
    def test_a_message_names_the_failing_group_and_links_to_it(
        self,
        _name: str,
        kind: SourceKind,
        grouping_key: str,
        source_config: dict[str, Any],
        labels: dict[str, str],
        details: list[tuple[str, str]],
        path: str,
    ) -> None:
        describe = (
            describe_source_transition if kind == SourceKind.WAREHOUSE_SOURCE else describe_destination_transition
        )
        transition = AnnouncedTransition(
            grouping_key=grouping_key,
            kind=AlertEventKind.FIRING,
            episode_started_at=datetime(2026, 10, 1, tzinfo=UTC),
            value=None,
            labels=labels,
            condition={},
            source_config=source_config,
            error_message=None,
            occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        )

        description = describe(project_id=7, transition=transition)

        assert [(detail.label, detail.value) for detail in description.details] == details
        assert description.data_link is not None
        assert description.data_link.url.endswith(path)

    def _person(self, who: str) -> User:
        if who == "another_organization":
            other = Organization.objects.create(name="Elsewhere")
            return User.objects.create_and_join(other, "elsewhere@example.com", None)
        person = User.objects.create_and_join(self.organization, f"{who}@example.com", None)
        if who == "opted_out":
            person.partial_notification_settings = {"plugin_disabled": False}
            person.save()
        if who in ("no_project_access", "no_warehouse_access"):
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save(update_fields=["available_product_features"])
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save(update_fields=["level"])
        if who == "no_project_access":
            # A private project, which an organization member reaches only through an explicit grant.
            AccessControl.objects.create(
                team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
            )
        if who == "no_warehouse_access":
            AccessControl.objects.create(team=self.team, resource="external_data_source", access_level="none")
        return person

    @parameterized.expand(
        [
            ("a_member", SourceKind.WAREHOUSE_SOURCE, "member", True, True),
            ("a_member_of_a_destination_alert", SourceKind.WAREHOUSE_DESTINATION, "member", True, True),
            ("nobody_when_the_alert_does_not_email", SourceKind.WAREHOUSE_SOURCE, "member", False, False),
            ("not_a_member_who_turned_off_pipeline_emails", SourceKind.WAREHOUSE_SOURCE, "opted_out", True, False),
            ("not_a_member_without_project_access", SourceKind.WAREHOUSE_SOURCE, "no_project_access", True, False),
            ("not_a_member_without_warehouse_access", SourceKind.WAREHOUSE_SOURCE, "no_warehouse_access", True, False),
            (
                "not_a_member_of_a_destination_alert_without_warehouse_access",
                SourceKind.WAREHOUSE_DESTINATION,
                "no_warehouse_access",
                True,
                False,
            ),
            ("not_a_user_of_another_organization", SourceKind.WAREHOUSE_SOURCE, "another_organization", True, False),
        ]
    )
    def test_an_alert_that_emails_project_members_reaches_who_pipeline_error_emails_reach(
        self, _name: str, kind: SourceKind, who: str, email_project_members: bool, reached: bool
    ) -> None:
        person = self._person(who)
        grouping_key = "source_id" if kind == SourceKind.WAREHOUSE_SOURCE else "destination_id"
        configuration_id = self._alert(kind, {"email_project_members": email_project_members}, grouping_key)
        expected = sorted([self.user.email, person.email] if reached else [self.user.email])

        assert project_member_emails(team_id=self.team.id, configuration_id=configuration_id) == (
            expected if email_project_members else []
        )

    def test_a_failing_table_emails_the_project_members_of_an_alert_that_emails_them(self) -> None:
        self._person("member")
        self._schema(self._source(), "charges", Status.FAILED)
        configuration_id = self._alert(
            SourceKind.WAREHOUSE_SOURCE, {"group_by": "source", "email_project_members": True}, "source_id"
        )
        evaluation = self._evaluate(SourceKind.WAREHOUSE_SOURCE)
        # The history that delivery reads is written when the record commits.
        with team_scope(self.team.id), self.captureOnCommitCallbacks(execute=True):
            record_outcomes(self.team.id, list(evaluation.outcomes), self.cutoff)
        (delivery,) = evaluation.deliveries

        with patch("products.alerts_platform.backend.delivery.email.EmailMessage") as email_message:
            sent = platform_testing.deliver(delivery)

        assert sent == 1
        assert delivery.configuration_id == str(configuration_id)
        assert "Sync failures" in email_message.call_args.kwargs["subject"]
        assert [call.kwargs["email"] for call in email_message.return_value.add_recipient.call_args_list] == sorted(
            [self.user.email, "member@example.com"]
        )
        email_message.return_value.send.assert_called_once_with()
