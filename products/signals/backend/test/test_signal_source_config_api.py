from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team

from products.signals.backend.models import SignalSourceConfig


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

    def test_update_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"enabled": False},
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
            config={},
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"config": {"recording_filters": {"duration_min": 30}}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["config"] == {"recording_filters": {"duration_min": 30}}

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
            ("evaluation_requires_row", SignalSourceConfig.SourceType.EVALUATION, None, False),
            ("evaluation_enabled_row", SignalSourceConfig.SourceType.EVALUATION, True, True),
            ("evaluation_report_requires_row", SignalSourceConfig.SourceType.EVALUATION_REPORT, None, False),
            ("evaluation_report_enabled_row", SignalSourceConfig.SourceType.EVALUATION_REPORT, True, True),
            ("evaluation_report_disabled_row", SignalSourceConfig.SourceType.EVALUATION_REPORT, False, False),
        ]
    )
    def test_llm_analytics_gating(self, _name, source_type, existing_enabled, expected):
        # llm_analytics has no always-on bypass: both evaluation and evaluation_report signals
        # go through the standard config-row check.
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

    @parameterized.expand(
        [
            ("no_row_defaults_on", None, True),
            ("explicit_disabled_opts_out", False, False),
            ("explicit_enabled_on", True, True),
        ]
    )
    def test_anomaly_investigation_source_on_by_default(self, _name, existing_enabled, expected):
        if existing_enabled is not None:
            SignalSourceConfig.objects.create(
                team=self.team,
                source_product=SignalSourceConfig.SourceProduct.ALERTS,
                source_type=SignalSourceConfig.SourceType.ANOMALY_INVESTIGATION,
                enabled=existing_enabled,
            )

        assert SignalSourceConfig.is_source_enabled(self.team.id, "alerts", "anomaly_investigation") is expected
