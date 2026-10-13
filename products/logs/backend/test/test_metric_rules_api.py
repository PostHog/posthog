from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.logs.backend.models import MAX_ENABLED_METRIC_RULES, LogsMetricRule
from products.logs.backend.presentation.views.metric_rules_api import LogsMetricRuleViewSet
from products.logs.backend.test.metric_rule_fixtures import VALID_FILTER_GROUP


class TestLogsMetricRulesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/metric_rules/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _payload(self, **overrides):
        data = {
            "name": "API errors",
            "metric_name": "log.api_errors",
            "filter_group": VALID_FILTER_GROUP,
        }
        data.update(overrides)
        return data

    @patch("products.logs.backend.presentation.views.metric_rules_api.report_user_action")
    def test_create_defaults(self, mock_report):
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["enabled"] is False
        assert body["version"] == 1
        assert body["value_attribute"] is None
        assert body["group_by"] == []
        mock_report.assert_called_once()

    def test_list_scoped_to_team(self):
        self.client.post(self.base_url, self._payload(), format="json")
        other_team = self.create_team_with_organization(organization=self.organization)
        with team_scope(other_team.id):
            LogsMetricRule.objects.create(team=other_team, name="other", metric_name="other.metric")

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["metric_name"] == "log.api_errors"

    def test_create_attribute_rule(self):
        response = self.client.post(
            self.base_url,
            self._payload(metric_name="log.request_duration", value_attribute="attributes.duration_ms"),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["value_attribute"] == "attributes.duration_ms"

    def test_rejects_duplicate_metric_name_for_team(self):
        assert self.client.post(self.base_url, self._payload(), format="json").status_code == status.HTTP_201_CREATED
        response = self.client.post(self.base_url, self._payload(name="Another"), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_rejects_enabling_more_than_max_rules(self):
        for i in range(MAX_ENABLED_METRIC_RULES):
            r = self.client.post(
                self.base_url,
                self._payload(name=f"r{i}", metric_name=f"log.m{i}", enabled=True),
                format="json",
            )
            assert r.status_code == status.HTTP_201_CREATED, r.json()
        response = self.client.post(
            self.base_url, self._payload(name="overflow", metric_name="log.overflow", enabled=True), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        # Disabled rules are not capped.
        response = self.client.post(
            self.base_url, self._payload(name="disabled", metric_name="log.disabled", enabled=False), format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_metric_name_and_value_attribute_immutable_on_update(self):
        created = self.client.post(self.base_url, self._payload(), format="json").json()
        detail_url = f"{self.base_url}{created['id']}/"

        response = self.client.patch(detail_url, {"metric_name": "log.renamed"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

        response = self.client.patch(detail_url, {"value_attribute": "attributes.duration_ms"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_update_filter_and_group_by_bumps_version(self):
        created = self.client.post(self.base_url, self._payload(), format="json").json()
        detail_url = f"{self.base_url}{created['id']}/"

        response = self.client.patch(detail_url, {"group_by": ["severity_text"], "enabled": True}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["group_by"] == ["severity_text"]
        assert body["enabled"] is True
        assert body["version"] == created["version"] + 1

    @parameterized.expand(
        [
            ("no flags", (), status.HTTP_403_FORBIDDEN),
            ("the retired logs flag alone", ("logs-metric-rules",), status.HTTP_403_FORBIDDEN),
            ("the metrics flag", ("metrics",), status.HTTP_201_CREATED),
        ]
    )
    def test_metrics_feature_flag_admits_the_team(
        self, _label: str, enabled_flags: tuple[str, ...], expected_status: int
    ) -> None:
        # A rule's output is only readable in Metrics, so that alpha flag is the one that admits a
        # team. `logs-metric-rules` is retired and must not open the API on its own.
        with patch("posthoganalytics.feature_enabled", side_effect=lambda flag, *_, **__: flag in enabled_flags):
            response = self.client.post(self.base_url, self._payload(), format="json")
            assert response.status_code == expected_status, response.json()

    def test_child_environment_url_targets_canonical_team(self):
        # RootTeamMixin.save() stores rules under the parent (canonical) team, so the
        # viewset must list, cap, and version-bump against that same canonical id — a
        # raw-child filter would hide the row and silently skip the version bump the
        # ingestion worker's cache coherency depends on.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        env_url = f"/api/projects/{env.pk}/logs/metric_rules/"

        created = self.client.post(env_url, self._payload(), format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        rule = LogsMetricRule.objects.unscoped().get(id=created.json()["id"])
        assert rule.team_id == self.team.pk

        listed = self.client.get(env_url)
        assert listed.status_code == status.HTTP_200_OK
        assert [r["id"] for r in listed.json()["results"]] == [created.json()["id"]]

        updated = self.client.patch(f"{env_url}{created.json()['id']}/", {"enabled": True}, format="json")
        assert updated.status_code == status.HTTP_200_OK, updated.json()
        assert updated.json()["version"] == created.json()["version"] + 1

    def test_child_scoped_personal_api_key_cannot_write_parent_rules(self):
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="child-scoped",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["logs:write", "metrics:write"],
            scoped_teams=[env.pk],
        )

        response = self.client.post(
            f"/api/projects/{env.pk}/logs/metric_rules/",
            self._payload(),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert LogsMetricRule.objects.unscoped().filter(team_id=self.team.pk).count() == 0

    def test_enabled_cap_counts_canonical_rows(self):
        # Rules created via the parent URL and a child URL land on the same canonical
        # team, so the cap must hold across both paths.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        for i in range(MAX_ENABLED_METRIC_RULES):
            r = self.client.post(
                self.base_url, self._payload(name=f"r{i}", metric_name=f"log.m{i}", enabled=True), format="json"
            )
            assert r.status_code == status.HTTP_201_CREATED, r.json()

        response = self.client.post(
            f"/api/projects/{env.pk}/logs/metric_rules/",
            self._payload(name="overflow", metric_name="log.overflow", enabled=True),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_write_requires_metrics_editor_access(self):
        # Metric rules publish log attribute values into the Metrics product, so rule
        # authors need authority over metrics too — a logs editor whose org restricted
        # metrics must not be able to export logs data through this side door. RBAC is
        # patched at the core boundary (creating an AccessControl row needs `ee`, which
        # products.logs may not depend on).
        def deny_metrics_only(resource, required_level=None, *args, **kwargs):
            return resource != "metrics"

        with patch(
            "products.logs.backend.presentation.views.metric_rules_api.UserAccessControl.check_access_level_for_resource",
            side_effect=deny_metrics_only,
        ) as mock_check:
            response = self.client.post(self.base_url, self._payload(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_check.assert_any_call("metrics", "editor")

    def test_delete_requires_metrics_editor_access(self):
        # Deleting a rule tears down a metric that metrics users may depend on, so it
        # is gated like create/update — a logs-only editor must not remove it. The
        # AccessControlPermission layer only evaluates the view's `logs` scope, so the
        # metrics check has to run in perform_destroy itself.
        created = self.client.post(self.base_url, self._payload(), format="json").json()
        detail_url = f"{self.base_url}{created['id']}/"

        def deny_metrics_only(resource, required_level=None, *args, **kwargs):
            return resource != "metrics"

        with patch(
            "products.logs.backend.presentation.views.metric_rules_api.UserAccessControl.check_access_level_for_resource",
            side_effect=deny_metrics_only,
        ):
            response = self.client.delete(detail_url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert self.client.get(detail_url).status_code == status.HTTP_200_OK

    def test_create_span_rule_requires_tracing_editor_access(self):
        # A spans rule's emitted series carry span attribute values readable by anyone
        # with metrics access — a user denied tracing access must not publish span data
        # past the tracing permission boundary through this side door.
        def deny_tracing_only(resource, required_level=None, *args, **kwargs):
            return resource != "tracing"

        with patch(
            "products.logs.backend.presentation.views.metric_rules_api.UserAccessControl.check_access_level_for_resource",
            side_effect=deny_tracing_only,
        ) as mock_check:
            response = self.client.post(self.base_url, self._payload(source="spans"), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_check.assert_any_call("tracing", "editor")

    def test_create_logs_rule_does_not_require_tracing_access(self):
        def deny_tracing_only(resource, required_level=None, *args, **kwargs):
            return resource != "tracing"

        with patch(
            "products.logs.backend.presentation.views.metric_rules_api.UserAccessControl.check_access_level_for_resource",
            side_effect=deny_tracing_only,
        ):
            response = self.client.post(self.base_url, self._payload(source="logs"), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_update_span_rule_requires_tracing_editor_access(self):
        created = self.client.post(self.base_url, self._payload(source="spans"), format="json").json()
        detail_url = f"{self.base_url}{created['id']}/"

        def deny_tracing_only(resource, required_level=None, *args, **kwargs):
            return resource != "tracing"

        with patch(
            "products.logs.backend.presentation.views.metric_rules_api.UserAccessControl.check_access_level_for_resource",
            side_effect=deny_tracing_only,
        ):
            response = self.client.patch(detail_url, {"name": "renamed"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_delete_span_rule_requires_tracing_editor_access(self):
        created = self.client.post(self.base_url, self._payload(source="spans"), format="json").json()
        detail_url = f"{self.base_url}{created['id']}/"

        def deny_tracing_only(resource, required_level=None, *args, **kwargs):
            return resource != "tracing"

        with patch(
            "products.logs.backend.presentation.views.metric_rules_api.UserAccessControl.check_access_level_for_resource",
            side_effect=deny_tracing_only,
        ):
            response = self.client.delete(detail_url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert self.client.get(detail_url).status_code == status.HTTP_200_OK

    def test_required_scopes_survive_schema_generation_context(self):
        # drf-spectacular calls dangerously_get_required_scopes with a mock request and
        # no team context for every action. It must not crash (KeyError on team_id) —
        # regressing this broke `hogli build:openapi`.
        view = LogsMetricRuleViewSet()
        view.action_map = {}
        for action in ("create", "update", "partial_update", "destroy", "list"):
            view.action = action
            view.kwargs = {}
            scopes = view.dangerously_get_required_scopes(Mock(data={}), view)
            if action in ("create", "update", "partial_update", "destroy"):
                assert scopes == ["logs:write", "metrics:write"], (action, scopes)
            else:
                assert scopes is None, (action, scopes)

    def test_span_rule_write_scopes_include_tracing_read(self):
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="no-tracing-scope",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["logs:write", "metrics:write"],
            scoped_teams=[self.team.pk],
        )

        response = self.client.post(
            self.base_url,
            self._payload(source="spans"),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

        response = self.client.post(
            self.base_url,
            self._payload(source="logs"),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

    @parameterized.expand(
        [
            (["logs:write"], status.HTTP_403_FORBIDDEN),
            (["logs:write", "metrics:write"], status.HTTP_201_CREATED),
        ]
    )
    def test_write_requires_metrics_write_scope_for_api_keys(self, scopes, expected_status):
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="scoped", user=self.user, secure_value=hash_key_value(key_value), scopes=scopes
        )

        response = self.client.post(
            self.base_url, self._payload(), format="json", HTTP_AUTHORIZATION=f"Bearer {key_value}"
        )
        assert response.status_code == expected_status, response.json()
