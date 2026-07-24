from datetime import UTC, datetime
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache

from rest_framework import status

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import Table, TableNode

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value, uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.actions.backend.models.action import Action
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.experiments.backend.session_context import MAX_SESSION_CONTEXT_BATCH, _query_stamped_flag_properties
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest
from ee.models.rbac.access_control import AccessControl

RECORDING_START = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
RECORDING_END = datetime(2026, 1, 1, 10, 30, 0, tzinfo=UTC)
SESSION_ID = str(uuid7(unix_ms_time=int(RECORDING_START.timestamp() * 1000)))
# A second recording on a different day, so batch tests exercise the per-day chunking path.
DAY_TWO_RECORDING_START = datetime(2025, 12, 31, 10, 0, 0, tzinfo=UTC)
DAY_TWO_RECORDING_END = datetime(2025, 12, 31, 10, 30, 0, tzinfo=UTC)
DAY_TWO_SESSION_ID = str(uuid7(unix_ms_time=int(DAY_TWO_RECORDING_START.timestamp() * 1000)))


def _hogql_table_tree(node: TableNode) -> dict[str, Any]:
    table = node.table
    return {
        "fields": sorted(table.fields) if isinstance(table, Table) else None,
        "children": {name: _hogql_table_tree(child) for name, child in node.children.items()},
    }


@freeze_time("2026-01-02T12:00:00Z")
class TestSessionExperimentContext(ClickhouseTestMixin, APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        # Every test shares SESSION_ID and the local-memory cache outlives a test; the context
        # cache key includes the per-test team, but clear anyway so no test can see another's entry.
        cache.clear()

    def _create_recording(self, session_id: str = SESSION_ID, team_id: Optional[int] = None) -> None:
        produce_replay_summary(
            team_id=team_id if team_id is not None else self.team.pk,
            session_id=session_id,
            distinct_id="user1",
            first_timestamp=RECORDING_START,
            last_timestamp=RECORDING_END,
        )

    def _create_experiment(
        self,
        key: str = "checkout-cta",
        name: str = "Checkout CTA copy",
        team: Optional[Team] = None,
        start_date: datetime = datetime(2025, 12, 1, tzinfo=UTC),
        end_date: Optional[datetime] = None,
        created_by: Optional[User] = None,
        exposure_criteria: Optional[dict[str, Any]] = None,
        metrics: Optional[list[dict[str, Any]]] = None,
    ) -> Experiment:
        team = team or self.team
        flag = FeatureFlag.objects.create(
            team=team,
            key=key,
            name=key,
            created_by=self.user,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                }
            },
        )
        return Experiment.objects.create(
            team=team,
            name=name,
            feature_flag=flag,
            created_by=created_by or self.user,
            start_date=start_date,
            end_date=end_date,
            exposure_criteria=exposure_criteria or {},
            metrics=metrics or [],
        )

    def _enable_access_controls(self, feature: str = AvailableFeature.ACCESS_CONTROL) -> None:
        features = self.organization.available_product_features or []
        if not any(existing["key"] == feature for existing in features):
            features.append({"key": feature, "name": feature})
            self.organization.available_product_features = features
            self.organization.save()

    def _create_session_event(
        self,
        event: str = "$feature_flag_called",
        timestamp: str = "2026-01-01T10:02:11Z",
        properties: Optional[dict[str, Any]] = None,
        session_id: str = SESSION_ID,
    ) -> None:
        _create_event(
            team=self.team,
            event=event,
            distinct_id="user1",
            timestamp=timestamp,
            properties={"$session_id": session_id, **(properties or {})},
        )

    def _get_session_context(self, session_id: Optional[str] = SESSION_ID) -> Any:
        params = {"session_id": session_id} if session_id is not None else {}
        return self.client.get(f"/api/projects/{self.team.id}/experiments/session_context/", params)

    def _post_session_contexts(self, session_ids: list[str]) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/experiments/session_contexts/",
            {"session_ids": session_ids},
            format="json",
        )

    def _create_day_two_recording_with_exposure(self, variant: str = "control") -> None:
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=DAY_TWO_SESSION_ID,
            distinct_id="user1",
            first_timestamp=DAY_TWO_RECORDING_START,
            last_timestamp=DAY_TWO_RECORDING_END,
        )
        self._create_session_event(
            timestamp="2025-12-31T10:03:00Z",
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": variant},
            session_id=DAY_TWO_SESSION_ID,
        )

    def test_requires_session_id(self) -> None:
        response = self._get_session_context(session_id=None)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_404_when_recording_missing(self) -> None:
        response = self._get_session_context()
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_returns_empty_when_no_running_experiments_overlap(self) -> None:
        self._create_recording()
        self._create_experiment(
            start_date=datetime(2025, 11, 1, tzinfo=UTC),
            end_date=datetime(2025, 12, 1, tzinfo=UTC),
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"session_id": SESSION_ID, "results": []}

    def test_resolves_variant_from_flag_called_event(self) -> None:
        self._create_recording()
        experiment = self._create_experiment()
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["session_id"] == SESSION_ID
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["experiment_id"] == experiment.id
        assert result["experiment_name"] == "Checkout CTA copy"
        assert result["flag_key"] == "checkout-cta"
        assert result["variant"] == "test"
        assert result["variants_seen"] == ["test"]
        assert result["multiple_variants"] is False
        assert result["first_exposure_timestamp"] == "2026-01-01T10:02:11Z"
        assert result["experiment_end_date"] is None

    def test_resolves_variant_from_stamped_properties_when_no_exposure_event(self) -> None:
        self._create_recording()
        experiment = self._create_experiment()
        self._create_session_event(
            event="$pageview",
            properties={"$feature/checkout-cta": "test"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["experiment_id"] == experiment.id
        assert results[0]["variant"] == "test"
        assert results[0]["variants_seen"] == ["test"]
        assert results[0]["multiple_variants"] is False
        assert results[0]["first_exposure_timestamp"] is None

    def test_multiple_variants_detected(self) -> None:
        self._create_recording()
        self._create_experiment()
        self._create_session_event(
            timestamp="2026-01-01T10:02:11Z",
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "control"},
        )
        self._create_session_event(
            timestamp="2026-01-01T10:05:00Z",
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["variant"] == "control"
        assert sorted(results[0]["variants_seen"]) == ["control", "test"]
        assert results[0]["multiple_variants"] is True
        assert results[0]["first_exposure_timestamp"] == "2026-01-01T10:02:11Z"

    def test_custom_exposure_event_defines_exposure_timestamp(self) -> None:
        self._create_recording()
        self._create_experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout started",
                    "properties": [],
                }
            }
        )
        # The flag evaluation happens first, but with a custom exposure event configured it
        # must not define the exposure moment.
        self._create_session_event(
            timestamp="2026-01-01T10:02:11Z",
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        self._create_session_event(
            event="checkout started",
            timestamp="2026-01-01T10:05:00Z",
            properties={"$feature/checkout-cta": "test"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["variant"] == "test"
        assert results[0]["variants_seen"] == ["test"]
        assert results[0]["first_exposure_timestamp"] == "2026-01-01T10:05:00Z"

    def test_custom_exposure_event_absent_yields_null_timestamp(self) -> None:
        self._create_recording()
        self._create_experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout started",
                    "properties": [],
                }
            }
        )
        # The session evaluated the flag but never fired the custom exposure event — the
        # flag-evaluation moment must not masquerade as an exposure timestamp.
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        self._create_session_event(event="$pageview", properties={"$feature/checkout-cta": "test"})
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["variant"] == "test"
        assert results[0]["first_exposure_timestamp"] is None

    def test_flag_evaluation_evidences_variant_for_custom_criteria(self) -> None:
        self._create_recording()
        self._create_experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout started",
                    "properties": [],
                }
            }
        )
        # Only a flag evaluation — no custom exposure event, no stamped properties (e.g.
        # server-evaluated flags). The replay still shows what the session was served, so the
        # experiment must surface with its variant; only the exposure moment stays undefined.
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["variant"] == "test"
        assert results[0]["variants_seen"] == ["test"]
        assert results[0]["first_exposure_timestamp"] is None

    def test_default_event_with_property_filters_defines_exposure_timestamp(self) -> None:
        self._create_recording()
        self._create_experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$feature_flag_called",
                    "properties": [{"key": "plan", "value": ["premium"], "operator": "exact", "type": "event"}],
                }
            }
        )
        # The experiment analysis applies the property filters even on the default event, so
        # the earlier non-matching flag call must not define the exposure moment — and the
        # variant must still come from $feature_flag_response (nothing stamps $feature/<key>).
        self._create_session_event(
            timestamp="2026-01-01T10:02:11Z",
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        self._create_session_event(
            timestamp="2026-01-01T10:06:00Z",
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test", "plan": "premium"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["variant"] == "test"
        assert results[0]["first_exposure_timestamp"] == "2026-01-01T10:06:00Z"

    def test_property_filters_respect_viewer_property_access_control(self) -> None:
        self._enable_access_controls(AvailableFeature.PROPERTY_ACCESS_CONTROL)
        self._create_recording()
        self._create_experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$feature_flag_called",
                    "properties": [{"key": "plan", "value": ["premium"], "operator": "exact", "type": "event"}],
                }
            }
        )
        # A user-specific denial leaves the default rules permissive, so it is only enforced
        # when the viewer threads through to the exposure queries — userless execution would
        # let the denied property's filter match and leak an exposure signal.
        plan_prop = PropertyDefinition.objects.create(
            team=self.team, name="plan", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        upsert_property_access_control(
            team_id=self.team.id,
            created_by_id=self.user.id,
            input=UpsertPropertyAccessControlInput(
                property_definition_id=str(plan_prop.id),
                access_level=PropertyAccessLevel.NONE,
                organization_member_id=self.organization_membership.id,
            ),
        )
        self._create_session_event(
            timestamp="2026-01-01T10:06:00Z",
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test", "plan": "premium"},
        )
        self._create_session_event(event="$pageview", properties={"$feature/checkout-cta": "test"})
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["variant"] == "test"
        assert results[0]["first_exposure_timestamp"] is None

    def test_unresolvable_property_filter_fails_soft(self) -> None:
        self._create_recording()
        # A duplicated experiment can carry a cohort id from its source project; resolving that
        # filter raises. One such experiment must not 500 the endpoint — it degrades to
        # stamped-property evidence with no exposure moment.
        self._create_experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout started",
                    "properties": [{"key": "id", "value": 999999, "type": "cohort"}],
                }
            }
        )
        self._create_session_event(event="$pageview", properties={"$feature/checkout-cta": "test"})
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["variant"] == "test"
        assert results[0]["first_exposure_timestamp"] is None

    def test_default_and_custom_experiments_sharing_a_flag_resolve_independently(self) -> None:
        self._create_recording()
        default_experiment = self._create_experiment(name="Default criteria")
        # Two experiments on one flag with different criteria — exposure evidence must stay
        # keyed by experiment id, not flag key: each takes its exposure moment from its own path.
        custom_experiment = Experiment.objects.create(
            team=self.team,
            name="Custom criteria",
            feature_flag=default_experiment.feature_flag,
            created_by=self.user,
            start_date=datetime(2025, 12, 1, tzinfo=UTC),
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout started",
                    "properties": [],
                }
            },
        )
        self._create_session_event(
            timestamp="2026-01-01T10:02:11Z",
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        self._create_session_event(
            event="checkout started",
            timestamp="2026-01-01T10:05:00Z",
            properties={"$feature/checkout-cta": "test"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        by_id = {result["experiment_id"]: result for result in results}
        assert by_id[default_experiment.id]["first_exposure_timestamp"] == "2026-01-01T10:02:11Z"
        assert by_id[custom_experiment.id]["first_exposure_timestamp"] == "2026-01-01T10:05:00Z"
        assert all(result["variant"] == "test" for result in results)

    def test_multiple_custom_criteria_experiments_resolve_in_one_request(self) -> None:
        self._create_recording()
        # Two custom-criteria experiments force a real multi-branch UNION ALL — a single branch
        # collapses to a plain SelectQuery, so only this shape proves the set query compiles
        # (a set-level LIMIT after the last branch's LIMIT 500ed the endpoint in production).
        first = self._create_experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout started",
                    "properties": [],
                }
            }
        )
        second = self._create_experiment(
            key="pricing-banner",
            name="Pricing banner",
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "pricing viewed",
                    "properties": [],
                }
            },
        )
        self._create_session_event(
            event="checkout started",
            timestamp="2026-01-01T10:05:00Z",
            properties={"$feature/checkout-cta": "test"},
        )
        self._create_session_event(
            event="pricing viewed",
            timestamp="2026-01-01T10:07:00Z",
            properties={"$feature/pricing-banner": "control"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        by_id = {result["experiment_id"]: result for result in results}
        assert by_id[first.id]["first_exposure_timestamp"] == "2026-01-01T10:05:00Z"
        assert by_id[second.id]["first_exposure_timestamp"] == "2026-01-01T10:07:00Z"

    def test_action_exposure_criteria_defines_exposure_timestamp(self) -> None:
        self._create_recording()
        action = Action.objects.create(team=self.team, name="Purchased", steps_json=[{"event": "purchase"}])
        self._create_experiment(
            exposure_criteria={"exposure_config": {"kind": "ActionsNode", "id": action.pk}},
        )
        self._create_session_event(
            event="purchase",
            timestamp="2026-01-01T10:07:00Z",
            properties={"$feature/checkout-cta": "control"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["variant"] == "control"
        assert results[0]["first_exposure_timestamp"] == "2026-01-01T10:07:00Z"

    def test_exposure_event_rescues_experiment_beyond_candidate_cap(self) -> None:
        self._create_recording()
        self._create_experiment(start_date=datetime(2025, 12, 1, tzinfo=UTC))
        self._create_experiment(key="newer-exp", name="Newer experiment", start_date=datetime(2025, 12, 15, tzinfo=UTC))
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        self._create_session_event(
            event="$pageview",
            properties={"$feature/checkout-cta": "control"},
        )
        flush_persons_and_events()

        # With the cap at 1, the newest-first slice keeps only "newer-exp" — the exposure
        # event for "checkout-cta" must still bring its experiment back into the results,
        # and the stamped-property query must cover the rescued flag's variants too.
        with patch("products.experiments.backend.session_context.MAX_CANDIDATE_EXPERIMENTS", 1):
            response = self._get_session_context()

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [result["flag_key"] for result in results] == ["checkout-cta"]
        assert results[0]["variant"] == "test"
        assert results[0]["variants_seen"] == ["control", "test"]
        assert results[0]["multiple_variants"] is True

    def test_ignores_non_enrolled_flag_responses(self) -> None:
        self._create_recording()
        self._create_experiment()
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": False},
        )
        self._create_session_event(
            event="$pageview",
            properties={"$feature/checkout-cta": True},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_ignores_flags_without_experiments(self) -> None:
        self._create_recording()
        self._create_experiment()
        FeatureFlag.objects.create(team=self.team, key="plain-flag", name="plain-flag", created_by=self.user)
        self._create_session_event(
            properties={"$feature_flag": "plain-flag", "$feature_flag_response": "true"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_resolves_experiment_amid_non_experiment_flag_calls(self) -> None:
        self._create_recording()
        experiment = self._create_experiment()
        # A non-experiment flag whose response collides with a defined variant name must not
        # surface anywhere, and must not stop the real experiment exposure from resolving.
        for key, response_value in [("plain-flag", "true"), ("colliding-flag", "control")]:
            FeatureFlag.objects.create(team=self.team, key=key, name=key, created_by=self.user)
            self._create_session_event(
                properties={"$feature_flag": key, "$feature_flag_response": response_value},
            )
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [result["flag_key"] for result in results] == ["checkout-cta"]
        assert results[0]["experiment_id"] == experiment.id
        assert results[0]["variant"] == "test"
        assert results[0]["variants_seen"] == ["test"]

    def test_excludes_private_experiments(self) -> None:
        self._enable_access_controls()
        other_user = self._create_user("other-experimenter@posthog.com")
        self._create_recording()
        self._create_experiment()
        private_experiment = self._create_experiment(
            key="private-exp", name="Private experiment", created_by=other_user
        )
        AccessControl.objects.create(
            team=self.team, resource="experiment", resource_id=str(private_experiment.pk), access_level="none"
        )
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        self._create_session_event(
            properties={"$feature_flag": "private-exp", "$feature_flag_response": "control"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        assert [result["flag_key"] for result in response.json()["results"]] == ["checkout-cta"]

    def test_cached_context_is_not_shared_across_users(self) -> None:
        self._enable_access_controls()
        other_user = self._create_user("other-experimenter@posthog.com")
        self._create_recording()
        self._create_experiment()
        private_experiment = self._create_experiment(
            key="private-exp", name="Private experiment", created_by=other_user
        )
        AccessControl.objects.create(
            team=self.team, resource="experiment", resource_id=str(private_experiment.pk), access_level="none"
        )
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        self._create_session_event(
            properties={"$feature_flag": "private-exp", "$feature_flag_response": "control"},
        )
        flush_persons_and_events()

        # Prime the cache as the private experiment's creator, who sees both experiments.
        self.client.force_login(other_user)
        response = self._get_session_context()
        assert [result["flag_key"] for result in response.json()["results"]] == ["checkout-cta", "private-exp"]

        # The cached entry must not leak the private experiment to a viewer without access.
        self.client.force_login(self.user)
        response = self._get_session_context()
        assert [result["flag_key"] for result in response.json()["results"]] == ["checkout-cta"]

    def test_repeat_request_is_served_from_cache(self) -> None:
        self._create_recording()
        self._create_experiment()
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        flush_persons_and_events()

        first = self._get_session_context()
        assert first.status_code == status.HTTP_200_OK

        with patch("products.experiments.backend.session_context._compute_session_experiment_contexts") as compute:
            second = self._get_session_context()
        compute.assert_not_called()
        assert second.json() == first.json()

    def test_uncached_request_shares_one_readonly_hogql_database(self) -> None:
        # Building the HogQL virtual database costs seconds on teams with a large warehouse
        # schema, so the endpoint builds one and shares it across every scan (exposures,
        # stamped properties, metric events) — concurrently, in production. Two regressions
        # pinned: a scan quietly building its own database (reintroduces the multi-second
        # latency), and a scan mutating the shared one (e.g. an information_schema-touching
        # query registers hidden external tables on it — a silent data race across the
        # production thread pool).
        self._create_recording()
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": "33333333-3333-3333-3333-333333333333",
            "name": "Purchases",
            "source": {"kind": "EventsNode", "event": "purchase"},
        }
        self._create_experiment(metrics=[metric])
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        self._create_session_event(event="purchase", timestamp="2026-01-01T10:09:00Z")
        flush_persons_and_events()

        built: list[tuple[Database, dict[str, Any]]] = []
        original_create_for = Database.create_for

        def _capturing_create_for(*args: Any, **kwargs: Any) -> Database:
            database = original_create_for(*args, **kwargs)
            built.append((database, _hogql_table_tree(database.tables)))
            return database

        with patch.object(Database, "create_for", side_effect=_capturing_create_for) as create_for:
            response = self._get_session_context()

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [result["flag_key"] for result in results] == ["checkout-cta"]
        assert results[0]["metrics_in_session"][0]["metric_uuid"] == metric["uuid"]
        assert create_for.call_count == 1
        database, tree_before_scans = built[0]
        assert _hogql_table_tree(database.tables) == tree_before_scans

    def test_recording_not_found_is_not_cached(self) -> None:
        # A recording can 404 while still ingesting; that answer must not stick for the TTL.
        assert self._get_session_context().status_code == status.HTTP_404_NOT_FOUND

        self._create_recording()
        self._create_experiment()
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        assert [result["flag_key"] for result in response.json()["results"]] == ["checkout-cta"]

    def test_403_without_session_recording_resource_access(self) -> None:
        self._enable_access_controls()
        AccessControl.objects.create(team=self.team, resource="session_recording", access_level="none")
        self._create_recording()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_requires_session_recording_read_scope(self) -> None:
        self._create_recording()
        self.client.logout()

        def _personal_api_key(scopes: list[str]) -> str:
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(user=self.user, label="t", secure_value=hash_key_value(token), scopes=scopes)
            return token

        token = _personal_api_key(["experiment:read"])
        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/session_context/",
            {"session_id": SESSION_ID},
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        token = _personal_api_key(["experiment:read", "session_recording:read"])
        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/session_context/",
            {"session_id": SESSION_ID},
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_metrics_in_session(self) -> None:
        self._create_recording()
        # Two overlapping experiments with a metric each force a multi-metric aggregate set in
        # the metric scan, proving the combined single-pass query compiles end to end through
        # the endpoint — and that a metric with no matching events stays inert.
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": "11111111-1111-1111-1111-111111111111",
            "name": "Purchases",
            "source": {"kind": "EventsNode", "event": "purchase"},
        }
        other_metric = {
            **metric,
            "uuid": "22222222-2222-2222-2222-222222222222",
            "name": "Pricing clicks",
            "source": {"kind": "EventsNode", "event": "pricing clicked"},
        }
        with_hit = self._create_experiment(metrics=[metric])
        without_hit = self._create_experiment(key="pricing-banner", name="Pricing banner", metrics=[other_metric])
        for key in ("checkout-cta", "pricing-banner"):
            self._create_session_event(properties={"$feature_flag": key, "$feature_flag_response": "test"})
        self._create_session_event(event="purchase", timestamp="2026-01-01T10:09:00Z")
        flush_persons_and_events()

        response = self._get_session_context()

        assert response.status_code == status.HTTP_200_OK
        by_id = {result["experiment_id"]: result for result in response.json()["results"]}
        assert by_id[with_hit.id]["metrics_in_session"] == [
            {
                "metric_uuid": metric["uuid"],
                "metric_name": "Purchases",
                "event_count": 1,
                "first_timestamp": "2026-01-01T10:09:00Z",
                "timestamps": ["2026-01-01T10:09:00Z"],
                "sources": [
                    {
                        "source_role": "source",
                        "source_name": "purchase",
                        "source_index": 0,
                        "source_total": 1,
                        "event_count": 1,
                        "first_timestamp": "2026-01-01T10:09:00Z",
                        "timestamps": ["2026-01-01T10:09:00Z"],
                    }
                ],
            }
        ]
        # No metric event fired for the other experiment — the additive fields stay inert and
        # every pre-existing field keeps its value (the no-regression claim for current consumers).
        assert by_id[without_hit.id] == {
            "experiment_id": without_hit.id,
            "experiment_name": "Pricing banner",
            "flag_key": "pricing-banner",
            "variant": "test",
            "variants_seen": ["test"],
            "multiple_variants": False,
            "first_exposure_timestamp": "2026-01-01T10:02:11Z",
            "experiment_start_date": "2025-12-01T00:00:00Z",
            "experiment_end_date": None,
            "metrics_in_session": [],
        }

    def test_metrics_in_session_includes_saved_metric(self) -> None:
        self._create_recording()
        inline_metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": "11111111-1111-1111-1111-111111111111",
            "name": "Purchases",
            "source": {"kind": "EventsNode", "event": "purchase"},
        }
        saved_query = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": "33333333-3333-3333-3333-333333333333",
            "name": "Signups",
            "source": {"kind": "EventsNode", "event": "signup"},
        }
        experiment = self._create_experiment(metrics=[inline_metric])
        saved = ExperimentSavedMetric.objects.create(team=self.team, name="Signups", query=saved_query)
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved, metadata={})
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        self._create_session_event(event="signup", timestamp="2026-01-01T10:08:00Z")
        self._create_session_event(event="purchase", timestamp="2026-01-01T10:09:00Z")
        flush_persons_and_events()

        response = self._get_session_context()

        assert response.status_code == status.HTTP_200_OK
        result = next(r for r in response.json()["results"] if r["experiment_id"] == experiment.id)
        # Both the inline and the saved/shared metric surface, sorted by first occurrence.
        assert [(hit["metric_uuid"], hit["metric_name"]) for hit in result["metrics_in_session"]] == [
            (saved_query["uuid"], "Signups"),
            (inline_metric["uuid"], "Purchases"),
        ]

    def test_team_isolation(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")

        other_team_session_id = str(uuid7(unix_ms_time=int(RECORDING_START.timestamp() * 1000)))
        self._create_recording(session_id=other_team_session_id, team_id=other_team.pk)
        response = self._get_session_context(session_id=other_team_session_id)
        assert response.status_code == status.HTTP_404_NOT_FOUND

        self._create_recording()
        self._create_experiment(key="other-team-flag", team=other_team)
        self._create_session_event(
            properties={"$feature_flag": "other-team-flag", "$feature_flag_response": "test"},
        )
        flush_persons_and_events()

        response = self._get_session_context()
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_batch_returns_same_items_as_single_calls(self) -> None:
        # Two sessions on different recording days force the day-chunked path, a custom-criteria
        # experiment forces the branch query, and a metric event in only one session forces
        # per-session metric attribution — all of which must produce exactly what N single
        # requests produce.
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": "11111111-1111-1111-1111-111111111111",
            "name": "Purchases",
            "source": {"kind": "EventsNode", "event": "purchase"},
        }
        self._create_experiment(metrics=[metric])
        self._create_experiment(
            key="pricing-banner",
            name="Pricing banner",
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout started",
                    "properties": [],
                }
            },
        )
        self._create_recording()
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        self._create_session_event(event="purchase", timestamp="2026-01-01T10:09:00Z")
        self._create_session_event(
            event="checkout started",
            timestamp="2026-01-01T10:05:00Z",
            properties={"$feature/pricing-banner": "test"},
        )
        self._create_day_two_recording_with_exposure(variant="control")
        flush_persons_and_events()

        singles = {
            session_id: self._get_session_context(session_id).json() for session_id in (SESSION_ID, DAY_TWO_SESSION_ID)
        }
        cache.clear()

        # The duplicate id must collapse to one entry, in request order.
        response = self._post_session_contexts([SESSION_ID, DAY_TWO_SESSION_ID, SESSION_ID])

        assert response.status_code == status.HTTP_200_OK
        entries = response.json()["results"]
        assert [entry["session_id"] for entry in entries] == [SESSION_ID, DAY_TWO_SESSION_ID]
        assert {entry["session_id"]: entry for entry in entries} == singles
        # Guard against "singles and batch are both wrong": pin the expected values too.
        day_one = {result["flag_key"]: result for result in entries[0]["results"]}
        assert day_one["checkout-cta"]["variant"] == "test"
        assert [hit["metric_uuid"] for hit in day_one["checkout-cta"]["metrics_in_session"]] == [metric["uuid"]]
        assert day_one["pricing-banner"]["first_exposure_timestamp"] == "2026-01-01T10:05:00Z"
        assert [
            (result["flag_key"], result["variant"], result["metrics_in_session"]) for result in entries[1]["results"]
        ] == [("checkout-cta", "control", [])]

    def test_batch_warms_cache_for_single_endpoint(self) -> None:
        self._create_recording()
        self._create_experiment()
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        flush_persons_and_events()

        batch = self._post_session_contexts([SESSION_ID])
        assert batch.status_code == status.HTTP_200_OK

        with patch("products.experiments.backend.session_context._compute_session_experiment_contexts") as compute:
            single = self._get_session_context()
        compute.assert_not_called()
        assert single.json() == batch.json()["results"][0]

    def test_batch_written_cache_is_not_shared_across_users(self) -> None:
        self._enable_access_controls()
        other_user = self._create_user("other-experimenter@posthog.com")
        self._create_recording()
        self._create_experiment()
        private_experiment = self._create_experiment(
            key="private-exp", name="Private experiment", created_by=other_user
        )
        AccessControl.objects.create(
            team=self.team, resource="experiment", resource_id=str(private_experiment.pk), access_level="none"
        )
        self._create_session_event(
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"},
        )
        self._create_session_event(
            properties={"$feature_flag": "private-exp", "$feature_flag_response": "control"},
        )
        flush_persons_and_events()

        # Prefetch as the private experiment's creator, who sees both experiments.
        self.client.force_login(other_user)
        response = self._post_session_contexts([SESSION_ID])
        assert [result["flag_key"] for result in response.json()["results"][0]["results"]] == [
            "checkout-cta",
            "private-exp",
        ]

        # The batch-written entry must not leak the private experiment to another viewer.
        self.client.force_login(self.user)
        response = self._get_session_context()
        assert [result["flag_key"] for result in response.json()["results"]] == ["checkout-cta"]

    def test_batch_omits_missing_recordings_and_never_caches_them(self) -> None:
        self._create_recording()
        self._create_experiment()
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        flush_persons_and_events()

        response = self._post_session_contexts([SESSION_ID, DAY_TWO_SESSION_ID])
        assert response.status_code == status.HTTP_200_OK
        assert [entry["session_id"] for entry in response.json()["results"]] == [SESSION_ID]

        # The missing recording finishes ingesting; the next batch must compute it rather
        # than serve a cached "absent".
        self._create_day_two_recording_with_exposure(variant="control")
        flush_persons_and_events()

        response = self._post_session_contexts([SESSION_ID, DAY_TWO_SESSION_ID])
        by_id = {entry["session_id"]: entry["results"] for entry in response.json()["results"]}
        assert [result["variant"] for result in by_id[DAY_TWO_SESSION_ID]] == ["control"]

    def test_batch_caps_candidates_per_day_chunk(self) -> None:
        # A newest-first candidate cap applied once over the whole batch's window can displace
        # an older experiment that a single request for an old recording would surface —
        # stamped-only evidence is never rescued. The cap must apply per day-chunk.
        self._create_experiment(
            key="old-exp",
            name="Old experiment",
            start_date=datetime(2025, 12, 1, tzinfo=UTC),
            end_date=datetime(2025, 12, 31, 23, 0, tzinfo=UTC),
        )
        self._create_experiment(key="new-exp", name="New experiment", start_date=datetime(2026, 1, 1, tzinfo=UTC))
        self._create_recording()
        self._create_session_event(event="$pageview", properties={"$feature/new-exp": "test"})
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=DAY_TWO_SESSION_ID,
            distinct_id="user1",
            first_timestamp=DAY_TWO_RECORDING_START,
            last_timestamp=DAY_TWO_RECORDING_END,
        )
        self._create_session_event(
            event="$pageview",
            timestamp="2025-12-31T10:03:00Z",
            properties={"$feature/old-exp": "control"},
            session_id=DAY_TWO_SESSION_ID,
        )
        flush_persons_and_events()

        with patch("products.experiments.backend.session_context.MAX_CANDIDATE_EXPERIMENTS", 1):
            response = self._post_session_contexts([SESSION_ID, DAY_TWO_SESSION_ID])

        assert response.status_code == status.HTTP_200_OK
        by_id = {entry["session_id"]: entry["results"] for entry in response.json()["results"]}
        assert [result["flag_key"] for result in by_id[SESSION_ID]] == ["new-exp"]
        assert [result["flag_key"] for result in by_id[DAY_TWO_SESSION_ID]] == ["old-exp"]

    def test_batch_caps_distinct_recording_days(self) -> None:
        # Ids scattered across many days would fan one throttled HTTP request out into a scan
        # set per day; only the most recent days within the budget are computed, and the rest
        # are omitted without being cached, so the single endpoint still computes them.
        self._create_recording()
        self._create_experiment()
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        self._create_day_two_recording_with_exposure()
        flush_persons_and_events()

        with patch("products.experiments.backend.session_context.MAX_SESSION_CONTEXT_BATCH_DAYS", 1):
            response = self._post_session_contexts([SESSION_ID, DAY_TWO_SESSION_ID])

        assert response.status_code == status.HTTP_200_OK
        assert [entry["session_id"] for entry in response.json()["results"]] == [SESSION_ID]

        single = self._get_session_context(DAY_TWO_SESSION_ID)
        assert [result["variant"] for result in single.json()["results"]] == ["control"]

    def test_batch_rejects_invalid_session_id_lists(self) -> None:
        assert self._post_session_contexts([]).status_code == status.HTTP_400_BAD_REQUEST
        over_cap = [str(uuid7()) for _ in range(MAX_SESSION_CONTEXT_BATCH + 1)]
        assert self._post_session_contexts(over_cap).status_code == status.HTTP_400_BAD_REQUEST

    def test_batch_builds_hogql_database_once(self) -> None:
        # Two sessions on different days run as two day-chunks; the expensive HogQL database
        # build must still happen once for the whole batch, not once per chunk or per scan.
        self._create_recording()
        self._create_experiment()
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        self._create_day_two_recording_with_exposure()
        flush_persons_and_events()

        original_create_for = Database.create_for
        with patch.object(Database, "create_for", side_effect=original_create_for) as create_for:
            response = self._post_session_contexts([SESSION_ID, DAY_TWO_SESSION_ID])

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 2
        assert create_for.call_count == 1

    def test_batch_failing_chunk_omits_only_its_sessions(self) -> None:
        # The batch prefetch is best-effort: one chunk's scans blowing up must not fail the
        # request (or poison the cache) for the other sessions.
        self._create_recording()
        self._create_experiment()
        self._create_session_event(properties={"$feature_flag": "checkout-cta", "$feature_flag_response": "test"})
        self._create_day_two_recording_with_exposure()
        flush_persons_and_events()

        def _explode_for_day_two(team: Any, user: Any, shared_hogql: Any, session_ids: list[str], *args: Any) -> Any:
            if DAY_TWO_SESSION_ID in session_ids:
                raise ValueError("simulated scan failure")
            return _query_stamped_flag_properties(team, user, shared_hogql, session_ids, *args)

        with patch(
            "products.experiments.backend.session_context._query_stamped_flag_properties",
            side_effect=_explode_for_day_two,
        ):
            response = self._post_session_contexts([SESSION_ID, DAY_TWO_SESSION_ID])

        assert response.status_code == status.HTTP_200_OK
        assert [entry["session_id"] for entry in response.json()["results"]] == [SESSION_ID]

    def test_batch_requires_session_recording_read_scope(self) -> None:
        self._create_recording()
        self.client.logout()

        def _personal_api_key(scopes: list[str]) -> str:
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(user=self.user, label="t", secure_value=hash_key_value(token), scopes=scopes)
            return token

        token = _personal_api_key(["experiment:read"])
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/session_contexts/",
            {"session_ids": [SESSION_ID]},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        token = _personal_api_key(["experiment:read", "session_recording:read"])
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/session_contexts/",
            {"session_ids": [SESSION_ID]},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK
