from copy import deepcopy

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from pydantic import JsonValue
from rest_framework.exceptions import ValidationError

from posthog.api.utils import ServiceRequest
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.dependency_formats import DEPENDENCY_BATCH_SIZE
from products.feature_flags.backend.facade.api import create_flag, set_flag_active, update_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def dependency_filters(*targets: FeatureFlag, value: bool | str = True) -> dict[str, JsonValue]:
    return {
        "groups": [
            {
                "properties": [
                    {"key": target.id, "type": "flag", "value": value, "operator": "flag_evaluates_to"}
                    for target in targets
                ],
                "rollout_percentage": 100,
            }
        ]
    }


class TestFeatureFlagDependencyFormats(APIBaseTest):
    def make_flag(self, key: str, **kwargs: object) -> FeatureFlag:
        return FeatureFlag.objects.create(team=self.team, key=key, **kwargs)

    @parameterized.expand(
        [
            (f"{method}_{index}_{mode}", method, version, rules)
            for method in ["post", "put", "patch"]
            for index, version in enumerate([2, 2.0, 3, 1.5, "1", "2", True, False, None])
            for mode, rules in [
                ("log", set()),
                ("partial", {"cross_field.variant_rollout_sum_not_100"}),
                ("full", {"*"}),
            ]
        ]
    )
    def test_non_v1_target_is_rejected_without_writes(
        self, _name: str, method: str, version: int | float | str | bool | None, rules: set[str]
    ) -> None:
        target_filters: dict[str, JsonValue] = {
            "version": version,
            "groups": "invalid",
            "rules": [],
            "seed": "invented-seed",
        }
        target = self.make_flag("target", filters=target_filters, version=42)
        source = self.make_flag("source", filters=dependency_filters(), version=7)
        before = deepcopy(source.filters)
        history_count = ActivityLog.objects.filter(team_id=self.team.id).count()
        url = f"/api/projects/{self.team.id}/feature_flags/"
        if method != "post":
            url += f"{source.id}/"
        with (
            override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES=rules),
            patch("products.feature_flags.backend.api.feature_flag.report_user_action") as report,
        ):
            response = getattr(self.client, method)(
                url,
                {"key": "new-source" if method == "post" else source.key, "filters": dependency_filters(target)},
                format="json",
            )
        assert response.status_code == 400, response.json()
        assert response.json()["code"] == "unsupported_dependency_config_version"
        assert response.json()["attr"] == "filters"
        assert response.json()["detail"] == (
            f"Flag dependency with ID {target.id} uses an unsupported configuration format. "
            "Remove this dependency to continue."
        )
        report.assert_not_called()
        assert ActivityLog.objects.filter(team_id=self.team.id).count() == history_count
        assert not FeatureFlag.objects.filter(team=self.team, key="new-source").exists()
        source.refresh_from_db()
        target.refresh_from_db()
        assert (source.filters, source.version) == (before, 7)
        assert (target.filters, target.version) == (target_filters, 42)

    @parameterized.expand([(None, True), (1, False), (1.0, "blue")])
    def test_v1_targets_keep_normalization_and_expected_values(
        self, version: int | float | None, value: bool | str
    ) -> None:
        target = self.make_flag(
            "target", filters={"groups": [], **({"version": version} if version else {})}, version=42
        )
        filters = dependency_filters(target, value=value)
        created = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", {"key": "source", "filters": filters}, format="json"
        )
        assert created.status_code == 201, created.json()
        updated = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{created.json()['id']}/",
            {"filters": {"payloads": {"true": '"sample"'}}},
            format="json",
        )
        assert updated.status_code == 200, updated.json()
        prop = updated.json()["filters"]["groups"][0]["properties"][0]
        assert prop == {"key": str(target.id), "type": "flag", "value": value, "operator": "flag_evaluates_to"}

    @parameterized.expand(
        [("leaf", {}), ("misleading", {"groups": [{"properties": []}]}), ("malformed", {"groups": [None]})]
    )
    def test_transitive_non_v1_target_is_not_a_leaf(self, _name: str, shape: dict[str, JsonValue]) -> None:
        target = self.make_flag("target", filters={"version": 2, **shape})
        middle = self.make_flag("middle", filters=dependency_filters(target))
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "source", "filters": dependency_filters(middle)},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "unsupported_dependency_config_version"
        assert response.json()["detail"] == (
            f"Flag dependency with ID {target.id} uses an unsupported configuration format. "
            "Remove this dependency to continue."
        )

    @parameterized.expand([("group", False, False), ("mixed", True, False), ("malformed", False, True)])
    @override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES=set())
    def test_aggregation_and_log_only_shapes_cannot_bypass_format_check(
        self, _name: str, mixed: bool, malformed: bool
    ) -> None:
        target = self.make_flag("target", filters={"version": 2})
        filters = dependency_filters(target)
        groups = filters["groups"]
        assert isinstance(groups, list) and isinstance(groups[0], dict)
        groups[0]["aggregation_group_type_index"] = 0
        if mixed:
            groups.append({"properties": [], "rollout_percentage": 100})
        if malformed:
            groups.append(None)
            source = self.make_flag("source", filters=filters)
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{source.id}/",
                {"filters": {"payloads": {"true": "1"}}},
                format="json",
            )
        else:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/", {"key": "source", "filters": filters}, format="json"
            )
        assert response.status_code == 400, response.json()
        assert response.json()["code"] == "unsupported_dependency_config_version"
        assert response.json()["detail"] == (
            f"Flag dependency with ID {target.id} uses an unsupported configuration format. "
            "Remove this dependency to continue."
        )

    @parameterized.expand(
        [
            ("omitted", {}, 200),
            ("empty", {"filters": {}}, 200),
            ("merge", {"filters": {"payloads": {"true": "1"}}}, 400),
            ("remove", {"filters": {"groups": []}}, 200),
        ]
    )
    def test_merged_candidate_and_metadata_compatibility(
        self, _name: str, data: dict[str, JsonValue], expected: int
    ) -> None:
        target = self.make_flag("target", filters={"version": 2})
        source = self.make_flag("source", filters=dependency_filters(target), version=7)
        before = deepcopy(source.filters)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{source.id}/", {"name": "Changed", **data}, format="json"
        )
        assert response.status_code == expected, response.json()
        source.refresh_from_db()
        assert source.version == (7 if expected == 400 else 8)
        assert source.filters == ({"groups": []} if _name == "remove" else before)

    @parameterized.expand(
        [
            ("enable_patch", "patch", False),
            ("enable_empty_filters", "empty", False),
            ("enable_action", "action", False),
            ("restore_active", "restore", False),
            ("enable_action_transitive", "action", True),
        ]
    )
    def test_enabling_or_restoring_checks_stored_reachable_formats(
        self, _name: str, mode: str, transitive: bool
    ) -> None:
        target = self.make_flag("target", filters={"version": 2})
        dependency = self.make_flag("middle", filters=dependency_filters(target)) if transitive else target
        source = self.make_flag(
            "source",
            filters=dependency_filters(dependency),
            active=mode == "restore",
            deleted=mode == "restore",
            version=7,
        )
        url = f"/api/projects/{self.team.id}/feature_flags/{source.id}/"
        if mode == "action":
            response = self.client.post(f"{url}enable/", {}, format="json")
        elif mode == "restore":
            response = self.client.patch(url, {"deleted": False}, format="json")
        elif mode == "empty":
            response = self.client.patch(url, {"active": True, "filters": {}}, format="json")
        else:
            response = self.client.patch(url, {"active": True}, format="json")
        assert response.status_code == 400, response.json()
        assert response.json()["code"] == "unsupported_dependency_config_version"
        assert response.json()["detail"] == (
            f"Flag dependency with ID {target.id} uses an unsupported configuration format. "
            "Remove this dependency to continue."
        )
        source.refresh_from_db()
        assert source.version == 7

    @parameterized.expand([("disable",), ("archive",), ("delete",), ("bulk_delete",)])
    def test_restrictive_actions_do_not_require_graph_repair(self, action: str) -> None:
        target = self.make_flag("target", filters={"version": 2})
        source = self.make_flag("source", filters=dependency_filters(target))
        url = f"/api/projects/{self.team.id}/feature_flags/"
        if action == "delete":
            response = self.client.patch(f"{url}{source.id}/", {"deleted": True}, format="json")
        elif action == "bulk_delete":
            response = self.client.post(f"{url}bulk_delete/", {"ids": [source.id]}, format="json")
        else:
            response = self.client.post(f"{url}{source.id}/{action}/", {}, format="json")
        assert response.status_code in (200, 204), response.content

    @parameterized.expand([("user", False), ("system", True)])
    def test_facade_writes_use_the_same_boundary(self, _name: str, system: bool) -> None:
        target = self.make_flag("target", filters={"version": 2})
        source = self.make_flag("source", filters=dependency_filters(target), active=False, version=7)
        actor = None if system else self.user
        for write in (
            lambda: create_flag(
                {"key": "new-source", "filters": dependency_filters(target)}, team=self.team, user=actor
            ),
            lambda: update_flag(source, {"filters": {"payloads": {"true": "1"}}}, team=self.team, user=actor),
            lambda: set_flag_active(source, True, team=self.team, user=actor),
        ):
            with self.assertRaises(ValidationError) as exc:
                write()
            assert exc.exception.get_codes() == {"filters": ["unsupported_dependency_config_version"]}
        source.refresh_from_db()
        assert not source.active
        assert source.version == 7

    def test_out_of_project_target_keeps_missing_reference_error(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        target = FeatureFlag.objects.create(team=other_team, key="private-target", filters={"version": 2})
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "source", "filters": dependency_filters(target)},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["detail"] == f"Flag dependency references non-existent flag with ID {target.id}"

    @parameterized.expand([(1, 201), (2, 400)])
    def test_reference_scope_remains_project_wide(self, version: int, expected: int) -> None:
        other_team = Team.objects.create(organization=self.organization, project=self.team.project)
        target = FeatureFlag.objects.create(
            team=other_team, key="other-environment-target", filters={"version": version, "groups": []}
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "source", "filters": dependency_filters(target)},
            format="json",
        )
        assert response.status_code == expected, response.json()
        if expected == 400:
            assert response.json()["code"] == "unsupported_dependency_config_version"

    @parameterized.expand([("inactive", False, False), ("deleted", True, True)])
    def test_reference_status_errors_precede_target_format(self, _name: str, active: bool, deleted: bool) -> None:
        target = self.make_flag("target", filters={"version": 2}, active=active, deleted=deleted)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "source", "filters": dependency_filters(target)},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_input"
        assert ("non-existent" if deleted else "disabled flag") in response.json()["detail"]

    def test_enabling_can_remove_a_forbidden_dependency(self) -> None:
        target = self.make_flag("target", filters={"version": 2})
        source = self.make_flag("source", filters=dependency_filters(target), active=False)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{source.id}/",
            {"active": True, "filters": {"groups": []}},
            format="json",
        )
        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.active
        assert source.filters["groups"] == []

    def test_restoring_disabled_flag_does_not_require_graph_repair(self) -> None:
        target = self.make_flag("target", filters={"version": 2})
        filters = dependency_filters(target)
        source = self.make_flag("source", filters=filters, active=False, deleted=True)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{source.id}/",
            {"deleted": False},
            format="json",
        )
        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert not source.deleted
        assert not source.active
        assert source.filters == filters

    @parameterized.expand(
        [("person", False, 2, 8), ("group", True, 2, 2), ("wide_group", True, DEPENDENCY_BATCH_SIZE + 1, 3)]
    )
    @override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES=set())
    def test_diamond_preserves_dependency_query_bound(
        self, _name: str, group_only: bool, width: int, query_limit: int
    ) -> None:
        leaf = self.make_flag("leaf", filters={"version": 1.0, "groups": []})
        branches = FeatureFlag.objects.bulk_create(
            [
                FeatureFlag(team=self.team, key=f"branch-{index}", filters=dependency_filters(leaf))
                for index in range(width)
            ]
        )
        candidate = dependency_filters(*branches)
        if group_only:
            groups = candidate["groups"]
            assert isinstance(groups, list) and isinstance(groups[0], dict)
            groups[0]["aggregation_group_type_index"] = 0
            FeatureFlag.objects.filter(id=leaf.id).update(filters=dependency_filters(leaf))
        serializer = FeatureFlagSerializer(
            data={"key": "source"}, context={"project_id": self.team.project_id, "request": ServiceRequest(self.user)}
        )
        with CaptureQueriesContext(connection) as queries:
            filters = serializer.validate_filters(candidate)
        assert [prop["key"] for prop in filters["groups"][0]["properties"]] == [str(flag.id) for flag in branches]
        assert len(queries) <= query_limit
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "source", "filters": candidate},
            format="json",
        )
        assert response.status_code == 201, response.json()
