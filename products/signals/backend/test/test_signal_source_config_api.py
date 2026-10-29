from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING

import pytest
from posthog.test.base import APIBaseTest

from django.db import connection, connections
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.serializers import SignalSourceConfigSerializer
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

if TYPE_CHECKING:
    from collections.abc import Callable


class TestSignalSourceConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Enabling `session_analysis_cluster` gates on org-level AI consent.
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

    def _url(self, config_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/signals/source_configs/"
        if config_id:
            return f"{base}{config_id}/"
        return base

    # --- Create ---

    def test_create_source_config(self):
        response = self.client.post(
            self._url(),
            data={
                "source_product": "session_replay",
                "source_type": "session_analysis_cluster",
                "enabled": True,
                "config": {"recording_filters": {"duration_min": 5}},
            },
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert data["source_product"] == "session_replay"
        assert data["source_type"] == "session_analysis_cluster"
        assert data["enabled"] is True
        # `sample_rate` is auto-set to the default for newly created session-analysis configs.
        assert data["config"] == {"recording_filters": {"duration_min": 5}, "sample_rate": 0.1}
        assert SignalSourceConfig.objects.filter(id=data["id"], team=self.team).exists()

    def test_create_source_config_sets_created_by(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        config = SignalSourceConfig.objects.get(id=response.json()["id"])
        assert config.created_by_id == self.user.id

    def test_create_source_config_defaults(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster"},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert data["enabled"] is True
        assert data["config"] == {"sample_rate": 0.1}

    def test_create_source_config_preserves_user_provided_sample_rate(self):
        response = self.client.post(
            self._url(),
            data={
                "source_product": "session_replay",
                "source_type": "session_analysis_cluster",
                "config": {"sample_rate": 0.5},
            },
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert data["config"] == {"sample_rate": 0.5}

    def test_create_source_config_no_default_for_other_source_types(self):
        # Defaulting only applies to session_replay/session_analysis_cluster.
        response = self.client.post(
            self._url(),
            data={"source_product": "github", "source_type": "issue", "enabled": False},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert data["config"] == {}

    def test_create_source_config_invalid_source_type(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "nonexistent_type"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "source_type" in str(response.json())

    def test_create_session_analysis_cluster_rejected_without_ai_consent(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        response = self.client.post(
            self._url(),
            data={
                "source_product": "session_replay",
                "source_type": "session_analysis_cluster",
                "enabled": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "AI data processing" in str(response.json())

    def test_create_session_analysis_cluster_allowed_when_disabled_without_consent(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        response = self.client.post(
            self._url(),
            data={
                "source_product": "session_replay",
                "source_type": "session_analysis_cluster",
                "enabled": False,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_duplicate_source_type_per_team_rejected(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in str(response.json())

    def test_same_source_type_allowed_on_different_teams(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        assert SignalSourceConfig.objects.filter(source_type="session_analysis_cluster").count() == 2

    # --- Config validation ---

    @parameterized.expand(
        [
            ("valid_recording_filters", {"recording_filters": {"duration_min": 5}}, status.HTTP_201_CREATED),
            ("empty_config", {}, status.HTTP_201_CREATED),
            ("recording_filters_not_dict", {"recording_filters": "bad"}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_create_config_validation(self, _name, config, expected_status):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster", "config": config},
            format="json",
        )
        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("valid_steering", {"steering": "Ignore issues labeled chore"}, status.HTTP_201_CREATED),
            ("steering_at_cap", {"steering": "x" * 2000}, status.HTTP_201_CREATED),
            ("steering_over_cap", {"steering": "x" * 2001}, status.HTTP_400_BAD_REQUEST),
            ("steering_not_string", {"steering": ["skip", "chores"]}, status.HTTP_400_BAD_REQUEST),
            ("valid_default_not_actionable", {"default_not_actionable": True}, status.HTTP_201_CREATED),
            ("default_not_actionable_not_bool", {"default_not_actionable": "yes"}, status.HTTP_400_BAD_REQUEST),
            (
                "both_keys_valid",
                {"steering": "Release checklists are never actionable", "default_not_actionable": False},
                status.HTTP_201_CREATED,
            ),
            # Falsy non-dict values must be rejected, not skipped by a truthiness guard.
            ("config_list", [], status.HTTP_400_BAD_REQUEST),
            ("config_string", "skip chores", status.HTTP_400_BAD_REQUEST),
            # Explicit nulls violate the key types and must not persist.
            ("steering_null", {"steering": None}, status.HTTP_400_BAD_REQUEST),
            ("default_not_actionable_null", {"default_not_actionable": None}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_create_steering_config_validation(self, _name, config, expected_status):
        # Steering keys are shared by every emission source, so they validate on a
        # non-session-replay source too.
        response = self.client.post(
            self._url(),
            data={"source_product": "github", "source_type": "issue", "enabled": False, "config": config},
            format="json",
        )
        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_201_CREATED:
            assert response.json()["config"] == config

    def test_create_linear_config_persists_team_ids(self):
        # Wiring guard for the serializer-level matrix in TestSignalSourceConfigSerializerValidation.
        config = {"linear_team_ids": ["team-1", "team-2"], "steering": "Skip chores"}
        response = self.client.post(
            self._url(),
            data={"source_product": "linear", "source_type": "issue", "config": config},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["config"] == config
        assert SignalSourceConfig.objects.get(id=response.json()["id"]).config == config

    # --- List ---

    def test_list_source_configs(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert len(data["results"]) == 1
        assert data["results"][0]["source_type"] == "session_analysis_cluster"

    def test_list_excludes_other_teams(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )

        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    # --- Retrieve ---

    def test_retrieve_source_config(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            config={"recording_filters": {"duration_min": 10}},
            created_by=self.user,
        )
        response = self.client.get(self._url(str(config.id)))
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert data["id"] == str(config.id)
        assert data["source_type"] == "session_analysis_cluster"
        assert data["config"] == {"recording_filters": {"duration_min": 10}}

    def test_retrieve_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.get(self._url(str(config.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand([({"enabled": False},), ({"config_set": {"steering": "Example"}},)])
    def test_update_other_teams_config_forbidden(self, body: dict[str, object]) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data=body,
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- Update ---

    def test_update_enabled(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            enabled=True,
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"enabled": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["enabled"] is False
        config.refresh_from_db()
        assert config.enabled is False

    def test_update_config(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            config={"steering": "Original guidance", "hogql_filter": "false"},
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"config": {"recording_filters": {"duration_min": 30}}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["config"] == {"recording_filters": {"duration_min": 30}}

    def test_config_key_updates_preserve_unrelated_settings(self) -> None:
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="linear",
            source_type="issue",
            config={"hogql_filter": "false", "default_not_actionable": True, "nested": {"keep": True}},
        )
        response = self.client.patch(
            self._url(str(config.id)),
            {
                "config_set": {"steering": "Prioritize documentation tasks"},
                "config_remove": ["default_not_actionable", "missing"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        response = self.client.patch(
            self._url(str(config.id)),
            {"config_set": {"linear_team_ids": [" team-example "], "nested": {"replace": True}, "nullable": None}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        config.refresh_from_db()
        assert config.config == {
            "hogql_filter": "false",
            "nested": {"replace": True},
            "nullable": None,
            "steering": "Prioritize documentation tasks",
            "linear_team_ids": ["team-example"],
        }
        assert response.json()["config"] == config.config
        assert "config_set" not in response.json()
        assert "config_remove" not in response.json()

    def test_invalid_merged_config_does_not_write_other_fields(self) -> None:
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="linear",
            source_type="issue",
            enabled=False,
            config={"linear_team_ids": "invalid", "default_not_actionable": True},
        )
        updated_at = config.updated_at
        response = self.client.patch(
            self._url(str(config.id)),
            {
                "enabled": True,
                "config_set": {"steering": "Review API documentation"},
                "config_remove": ["default_not_actionable"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        config.refresh_from_db()
        assert config.enabled is False
        assert config.config == {"linear_team_ids": "invalid", "default_not_actionable": True}
        assert config.updated_at == updated_at
        response = self.client.patch(self._url(str(config.id)), {"config_remove": ["linear_team_ids"]}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["config"] == {"default_not_actionable": True}

    def test_config_keys_require_write_scope(self) -> None:
        config = SignalSourceConfig.objects.create(team=self.team, source_product="linear", source_type="issue")
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["task:read"],
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        response = self.client.patch(
            self._url(str(config.id)),
            {"config_set": {"steering": "Review API documentation"}},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {raw}",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        config.refresh_from_db()
        assert config.config == {}

    def test_update_config_recording_filters_not_dict_rejected(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            config={},
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"config": {"recording_filters": [1, 2, 3]}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "recording_filters must be a JSON object" in str(response.json())

    def test_update_source_keys_are_immutable(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        for field, value in (("source_type", "issue_created"), ("source_product", "error_tracking")):
            response = self.client.patch(self._url(str(config.id)), data={field: value}, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        config.refresh_from_db()
        assert config.source_product == "session_replay"
        assert config.source_type == "session_analysis_cluster"

    def test_delete_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.delete(self._url(str(config.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SignalSourceConfig.objects.filter(id=config.id).exists()

    # --- Delete ---

    def test_delete_source_config(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        config_id = str(config.id)
        response = self.client.delete(self._url(config_id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SignalSourceConfig.objects.filter(id=config_id).exists()

    # --- Read-only fields ---

    def test_read_only_fields_in_response(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster"},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    # --- Auth ---

    def test_unauthenticated_request_rejected(self):
        self.client.logout()
        response = self.client.get(self._url())
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


class TestSignalSourceConfigSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ({"config_set": []},),
            ({"config_set": None},),
            ({"config_remove": "steering"},),
            ({"config_set": {"steering": "new"}, "config_remove": ["steering"]},),
            ({"config": {}, "config_set": {}},),
            ({"config": {}, "config_remove": []},),
            ({"config_set": {"steering": None}},),
            ({"config_set": {"linear_team_ids": "invalid"}},),
        ]
    )
    def test_invalid_config_key_updates(self, data: dict[str, object]) -> None:
        instance = SignalSourceConfig(source_product="linear", source_type="issue", config={"steering": "original"})
        serializer = SignalSourceConfigSerializer(instance, data=data, partial=True)
        assert not serializer.is_valid()
        assert instance.config == {"steering": "original"}

    def test_config_key_updates_are_rejected_on_create(self) -> None:
        serializer = SignalSourceConfigSerializer(
            data={"source_product": "linear", "source_type": "issue", "config_set": {}}
        )
        assert not serializer.is_valid()

    @parameterized.expand(
        [
            ("valid", {"linear_team_ids": ["team-1", "team-2"]}, True),
            ("empty_list_means_all_teams", {"linear_team_ids": []}, True),
            ("at_cap", {"linear_team_ids": [f"team-{i}" for i in range(100)]}, True),
            ("over_cap", {"linear_team_ids": [f"team-{i}" for i in range(101)]}, False),
            ("at_id_length_cap", {"linear_team_ids": ["t" * 255]}, True),
            ("over_id_length_cap", {"linear_team_ids": ["t" * 256]}, False),
            ("not_a_list", {"linear_team_ids": "team-1"}, False),
            ("null", {"linear_team_ids": None}, False),
            ("non_string_entry", {"linear_team_ids": ["team-1", 2]}, False),
            ("blank_entry", {"linear_team_ids": ["team-1", " "]}, False),
        ]
    )
    def test_linear_team_ids(self, _name, config, expected_valid):
        serializer = SignalSourceConfigSerializer(
            data={"source_product": "linear", "source_type": "issue", "config": config}
        )
        assert serializer.is_valid() is expected_valid, serializer.errors
        if not expected_valid:
            assert "linear_team_ids" in str(serializer.errors["config"])

    def test_linear_team_ids_are_stored_stripped(self):
        serializer = SignalSourceConfigSerializer(
            data={
                "source_product": "linear",
                "source_type": "issue",
                "config": {"linear_team_ids": [" team-1 ", "team-2"]},
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["config"]["linear_team_ids"] == ["team-1", "team-2"]


class TestScoutSourceCanonicalization(APIBaseTest):
    """The scout source config is a project-level singleton: the scout fleet canonicalizes child
    environments to the parent team and the emit preflight gates on the parent team's row, so the
    inbox toggle must read and write that same canonical row from any environment in the project."""

    def setUp(self) -> None:
        super().setUp()
        # A second environment within the same project, parented to the default team.
        self.child_team = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Child env"
        )

    def _child_url(self, config_id: str | None = None) -> str:
        base = f"/api/projects/{self.child_team.id}/signals/source_configs/"
        return f"{base}{config_id}/" if config_id else base

    def test_create_from_child_env_writes_canonical_team(self):
        response = self.client.post(
            self._child_url(),
            data={"source_product": "signals_scout", "source_type": "cross_source_issue", "enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        config = SignalSourceConfig.objects.get(id=response.json()["id"])
        # Written to the parent team, so the emit preflight (which canonicalizes) finds it.
        assert config.team_id == self.team.id
        assert SignalSourceConfig.is_source_enabled(self.team.id, "signals_scout", "cross_source_issue") is True

    def test_child_env_lists_canonical_scout_row(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="signals_scout",
            source_type="cross_source_issue",
            enabled=True,
        )
        results = self.client.get(self._child_url()).json()["results"]
        assert [r["id"] for r in results] == [str(config.id)]

    def test_child_env_updates_canonical_scout_row(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="signals_scout",
            source_type="cross_source_issue",
            enabled=True,
        )
        response = self.client.patch(self._child_url(str(config.id)), data={"enabled": False}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        config.refresh_from_db()
        assert config.enabled is False

    def test_child_env_cannot_retag_config_into_scout_source(self):
        # A child-environment row retagged to the scout source would otherwise stay on the child
        # team, hidden by the read filter while the emit gate checks the parent — a hidden, broken
        # scout config. Source keys are immutable on update, so the retag is rejected outright.
        config = SignalSourceConfig.objects.create(
            team=self.child_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            enabled=True,
        )
        response = self.client.patch(
            self._child_url(str(config.id)),
            data={"source_product": "signals_scout", "source_type": "cross_source_issue"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        config.refresh_from_db()
        assert config.team_id == self.child_team.id
        assert config.source_product == "session_replay"
        assert config.source_type == "session_analysis_cluster"
        # No stranded scout row exists on either team.
        assert not SignalSourceConfig.objects.filter(
            team_id__in=[self.team.id, self.child_team.id],
            source_product="signals_scout",
            source_type="cross_source_issue",
        ).exists()

    def test_non_scout_source_stays_environment_scoped(self):
        # A parent-team session-analysis row must not leak into the child environment's list.
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            enabled=True,
        )
        assert self.client.get(self._child_url()).json()["results"] == []

    def _child_scoped_api_key_auth(self) -> str:
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="child-scoped",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["task:read", "task:write"],
            scoped_teams=[self.child_team.id],
        )
        self.client.logout()
        return f"Bearer {raw}"

    def test_child_scoped_api_key_lists_only_child_rows(self):
        SignalSourceConfig.objects.create(
            team=self.team, source_product="signals_scout", source_type="cross_source_issue"
        )
        child_row = SignalSourceConfig.objects.create(
            team=self.child_team, source_product="session_replay", source_type="session_analysis_cluster"
        )
        response = self.client.get(self._child_url(), HTTP_AUTHORIZATION=self._child_scoped_api_key_auth())
        assert response.status_code == status.HTTP_200_OK
        assert [r["id"] for r in response.json()["results"]] == [str(child_row.id)]

    @parameterized.expand([("get",), ("patch",), ("delete",)])
    def test_child_scoped_api_key_cannot_touch_canonical_scout_row(self, method: str):
        scout_row = SignalSourceConfig.objects.create(
            team=self.team, source_product="signals_scout", source_type="cross_source_issue", enabled=True
        )
        response = getattr(self.client, method)(
            self._child_url(str(scout_row.id)),
            {"enabled": False},
            format="json",
            HTTP_AUTHORIZATION=self._child_scoped_api_key_auth(),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        scout_row.refresh_from_db()
        assert scout_row.enabled is True

    def test_child_scoped_api_key_cannot_create_canonical_scout_row(self):
        response = self.client.post(
            self._child_url(),
            {"source_product": "signals_scout", "source_type": "cross_source_issue", "enabled": False},
            format="json",
            HTTP_AUTHORIZATION=self._child_scoped_api_key_auth(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not SignalSourceConfig.objects.filter(source_product="signals_scout").exists()


class TestIsSourceEnabledGating(APIBaseTest):
    """Source-level gating quirks: session_problem routes through the session_analysis_cluster
    config rather than requiring its own SignalSourceConfig row."""

    def test_session_problem_gated_by_session_analysis_cluster(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            enabled=True,
        )

        assert SignalSourceConfig.is_source_enabled(self.team.id, "session_replay", "session_problem") is True

    def test_pganalyze_issue_requires_own_config(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.PGANALYZE,
            source_type=SignalSourceConfig.SourceType.ISSUE,
            enabled=True,
        )

        assert SignalSourceConfig.is_source_enabled(self.team.id, "pganalyze", "issue") is True

    def test_pganalyze_disabled_when_no_config(self):
        assert SignalSourceConfig.is_source_enabled(self.team.id, "pganalyze", "issue") is False

    def test_replay_vision_scanner_finding_is_self_authorizing(self):
        # The scanner's `emits_signals` flag is the config — no SignalSourceConfig row exists.
        assert SignalSourceConfig.is_source_enabled(self.team.id, "replay_vision", "scanner_finding") is True

    @parameterized.expand(
        [
            ("evaluation_report_requires_row", SignalSourceConfig.SourceType.EVALUATION_REPORT, None, False),
            ("evaluation_report_enabled_row", SignalSourceConfig.SourceType.EVALUATION_REPORT, True, True),
            ("evaluation_report_disabled_row", SignalSourceConfig.SourceType.EVALUATION_REPORT, False, False),
        ]
    )
    def test_llm_analytics_gating(self, _name, source_type, existing_enabled, expected):
        # llm_analytics has no always-on bypass: evaluation_report signals go through the
        # standard config-row check.
        if existing_enabled is not None:
            SignalSourceConfig.objects.create(
                team=self.team,
                source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
                source_type=source_type,
                enabled=existing_enabled,
            )

        assert SignalSourceConfig.is_source_enabled(self.team.id, "llm_analytics", source_type) is expected

    @parameterized.expand(
        [
            ("no_row_defaults_on", None, True),
            ("explicit_disabled_opts_out", False, False),
            ("explicit_enabled_on", True, True),
        ]
    )
    def test_scout_source_on_by_default(self, _name, existing_enabled, expected):
        if existing_enabled is not None:
            SignalSourceConfig.objects.create(
                team=self.team,
                source_product=SignalSourceConfig.SourceProduct.SIGNALS_SCOUT,
                source_type=SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE,
                enabled=existing_enabled,
            )

        assert SignalSourceConfig.is_source_enabled(self.team.id, "signals_scout", "cross_source_issue") is expected


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("status_lookup_fails", [False, True])
def test_concurrent_config_key_updates_preserve_both_edits(status_lookup_fails: bool) -> None:
    organization = Organization.objects.create(name="Config concurrency test")
    team = Team.objects.create(organization=organization)
    user = User.objects.create(email="config-editor@example.com")
    organization.members.add(user)
    config = SignalSourceConfig.objects.create(
        team=team,
        source_product="linear",
        source_type="issue",
        enabled=False,
        config={"hogql_filter": "false", "default_not_actionable": True},
    )
    barrier = Barrier(2)

    def update_config(body: dict[str, object]) -> int:
        failed_status_reads: list[str] = []

        def fail_status_read(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: dict[str, object]
        ) -> object:
            if status_lookup_fails and ExternalDataSchema._meta.db_table in sql:
                failed_status_reads.append(sql)
                return execute("SELECT 1 / 0", None, many, context)
            return execute(sql, params, many, context)

        try:
            client = APIClient()
            client.force_authenticate(user)
            barrier.wait(timeout=10)
            with connection.execute_wrapper(fail_status_read):
                response = client.patch(
                    f"/api/projects/{team.id}/signals/source_configs/{config.id}/", body, format="json"
                )
            assert bool(failed_status_reads) is status_lookup_fails
            assert response.status_code == status.HTTP_200_OK, response.json()
            return response.status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        updates: list[dict[str, object]] = [
            {"config_set": {"steering": "Prioritize documentation tasks"}, "config_remove": ["default_not_actionable"]},
            {"config_set": {"linear_team_ids": ["team-example"]}},
        ]
        futures = [pool.submit(update_config, body) for body in updates]
        for future in futures:
            future.result(timeout=20)
    config.refresh_from_db()
    assert config.config == {
        "hogql_filter": "false",
        "steering": "Prioritize documentation tasks",
        "linear_team_ids": ["team-example"],
    }
