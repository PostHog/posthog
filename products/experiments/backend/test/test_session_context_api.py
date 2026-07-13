from datetime import UTC, datetime
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value, uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest
from ee.models.rbac.access_control import AccessControl

RECORDING_START = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
RECORDING_END = datetime(2026, 1, 1, 10, 30, 0, tzinfo=UTC)
SESSION_ID = str(uuid7(unix_ms_time=int(RECORDING_START.timestamp() * 1000)))


@freeze_time("2026-01-02T12:00:00Z")
class TestSessionExperimentContext(ClickhouseTestMixin, APILicensedTest):
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
        )

    def _enable_access_controls(self) -> None:
        features = self.organization.available_product_features or []
        if not any(feature["key"] == AvailableFeature.ACCESS_CONTROL for feature in features):
            features.append({"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL})
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
        assert result["first_flag_evaluation_timestamp"] == "2026-01-01T10:02:11Z"
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
        assert results[0]["first_flag_evaluation_timestamp"] is None

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
        assert results[0]["first_flag_evaluation_timestamp"] == "2026-01-01T10:02:11Z"

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
