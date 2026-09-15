from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team

from products.signals.backend.models import SignalSourceConfig


class TestSignalSourceConfigAPI(APIBaseTest):
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
                "source_product": "pganalyze",
                "source_type": "issue",
                "enabled": True,
                "config": {"steering": "Ignore issues labeled chore"},
            },
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert data["source_product"] == "pganalyze"
        assert data["source_type"] == "issue"
        assert data["enabled"] is True
        assert data["config"] == {"steering": "Ignore issues labeled chore"}
        assert SignalSourceConfig.objects.filter(id=data["id"], team=self.team).exists()

    def test_create_source_config_sets_created_by(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "pganalyze", "source_type": "issue"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        config = SignalSourceConfig.objects.get(id=response.json()["id"])
        assert config.created_by_id == self.user.id

    def test_create_source_config_defaults(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "pganalyze", "source_type": "issue"},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert data["enabled"] is True
        assert data["config"] == {}

    @parameterized.expand(
        [
            ("unknown_type", "nonexistent_type"),
            # Retired sources stay in the signal taxonomy so old signals still resolve to a label,
            # but they carry no config row, so a team cannot turn one back on.
            ("retired_session_analysis_cluster", "session_analysis_cluster"),
            ("retired_session_problem", "session_problem"),
            ("retired_evaluation", "evaluation"),
        ]
    )
    def test_create_source_config_unsupported_source_type(self, _name, source_type):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": source_type},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "source_type" in str(response.json())

    def test_create_duplicate_source_type_per_team_rejected(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )
        response = self.client.post(
            self._url(),
            data={"source_product": "pganalyze", "source_type": "issue"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in str(response.json())

    def test_same_source_type_allowed_on_different_teams(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        SignalSourceConfig.objects.create(
            team=other_team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )
        assert SignalSourceConfig.objects.filter(source_type="issue").count() == 2

    # --- Config validation ---

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
        # Steering keys are shared by every emission source.
        response = self.client.post(
            self._url(),
            data={"source_product": "github", "source_type": "issue", "enabled": False, "config": config},
            format="json",
        )
        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_201_CREATED:
            assert response.json()["config"] == config

    # --- List ---

    def test_list_source_configs(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert len(data["results"]) == 1
        assert data["results"][0]["source_type"] == "issue"

    def test_list_excludes_other_teams(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        SignalSourceConfig.objects.create(
            team=other_team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )

        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    # --- Retrieve ---

    def test_retrieve_source_config(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="pganalyze",
            source_type="issue",
            config={"steering": "Only page on replication lag"},
            created_by=self.user,
        )
        response = self.client.get(self._url(str(config.id)))
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert data["id"] == str(config.id)
        assert data["source_type"] == "issue"
        assert data["config"] == {"steering": "Only page on replication lag"}

    def test_retrieve_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )
        response = self.client.get(self._url(str(config.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="pganalyze",
            source_type="issue",
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
            source_product="pganalyze",
            source_type="issue",
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
            source_product="pganalyze",
            source_type="issue",
            config={},
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"config": {"steering": "Only page on replication lag"}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["config"] == {"steering": "Only page on replication lag"}

    def test_update_source_keys_are_immutable(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )
        for field, value in (("source_type", "issue_created"), ("source_product", "error_tracking")):
            response = self.client.patch(self._url(str(config.id)), data={field: value}, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        config.refresh_from_db()
        assert config.source_product == "pganalyze"
        assert config.source_type == "issue"

    def test_delete_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="pganalyze",
            source_type="issue",
            created_by=self.user,
        )
        response = self.client.delete(self._url(str(config.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SignalSourceConfig.objects.filter(id=config.id).exists()

    # --- Delete ---

    def test_delete_source_config(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="pganalyze",
            source_type="issue",
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
            data={"source_product": "pganalyze", "source_type": "issue"},
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
            source_product="pganalyze",
            source_type="issue",
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
        assert config.source_product == "pganalyze"
        assert config.source_type == "issue"
        # No stranded scout row exists on either team.
        assert not SignalSourceConfig.objects.filter(
            team_id__in=[self.team.id, self.child_team.id],
            source_product="signals_scout",
            source_type="cross_source_issue",
        ).exists()

    def test_non_scout_source_stays_environment_scoped(self):
        # A parent-team pganalyze row must not leak into the child environment's list.
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="pganalyze",
            source_type="issue",
            enabled=True,
        )
        assert self.client.get(self._child_url()).json()["results"] == []


class TestIsSourceEnabledGating(APIBaseTest):
    """Source-level gating quirks: which sources bypass the SignalSourceConfig row check."""

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
