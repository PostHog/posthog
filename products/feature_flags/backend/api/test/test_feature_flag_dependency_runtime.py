from collections.abc import Callable

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _depends_on(*flag_ids: int, rollout_percentage: int = 100) -> dict:
    return {
        "groups": [
            {
                "properties": [
                    {"key": str(flag_id), "type": "flag", "value": "true", "operator": "flag_evaluates_to"}
                    for flag_id in flag_ids
                ],
                "rollout_percentage": rollout_percentage,
            }
        ]
    }


class TestFeatureFlagDependencyRuntime(APIBaseTest):
    def _flag(self, key: str, runtime: str | None, filters: dict | None = None, active: bool = True) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key=key,
            active=active,
            evaluation_runtime=runtime,
            filters=filters or {"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

    def _patch(self, flag: FeatureFlag, data: dict):
        return self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", data, format="json")

    @parameterized.expand(
        [
            ("server_on_client", "server", "client", False),
            ("client_on_server", "client", "server", False),
            ("all_on_client", "all", "client", False),
            ("all_on_server", "all", "server", False),
            ("unset_on_client", None, "client", False),
            ("server_on_server", "server", "server", True),
            ("client_on_all", "client", "all", True),
            ("server_on_unset", "server", None, True),
            ("all_on_all", "all", "all", True),
        ]
    )
    def test_create_checks_dependency_runtime(
        self, _name: str, dependent_runtime: str | None, dependency_runtime: str | None, allowed: bool
    ) -> None:
        dependency = self._flag("dependency", dependency_runtime)
        payload: dict = {"key": "dependent", "filters": _depends_on(dependency.id)}
        if dependent_runtime is not None:
            payload["evaluation_runtime"] = dependent_runtime

        response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/", payload, format="json")

        if allowed:
            assert response.status_code == status.HTTP_201_CREATED, response.json()
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert response.json()["attr"] == "filters"
            assert f"Cannot depend on flag 'dependency' (ID: {dependency.id})" in response.json()["detail"]

    @parameterized.expand([("keeping_the_dependency", True), ("removing_the_dependency", False)])
    def test_changing_runtime_checks_the_flags_own_dependencies(self, _name: str, keep_dependency: bool) -> None:
        dependency = self._flag("dependency", "client")
        dependent = self._flag("dependent", "client", filters=_depends_on(dependency.id))
        data: dict = {"evaluation_runtime": "server"}
        if not keep_dependency:
            data["filters"] = _depends_on()

        response = self._patch(dependent, data)

        if keep_dependency:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert response.json()["attr"] == "evaluation_runtime"
            assert response.json()["code"] == "dependency_runtime_mismatch"
            dependent.refresh_from_db()
            assert dependent.evaluation_runtime == "client"
        else:
            assert response.status_code == status.HTTP_200_OK, response.json()

    @parameterized.expand(
        [
            ("hides_from_active_dependent", "client", True, False),
            ("matches_active_dependent", "server", True, True),
            ("hides_from_disabled_dependent", "client", False, True),
        ]
    )
    def test_changing_runtime_checks_dependents(
        self, _name: str, new_runtime: str, dependent_active: bool, allowed: bool
    ) -> None:
        dependency = self._flag("dependency", "all")
        dependent = self._flag("dependent", "server", filters=_depends_on(dependency.id), active=dependent_active)

        response = self._patch(dependency, {"evaluation_runtime": new_runtime})

        if allowed:
            assert response.status_code == status.HTTP_200_OK, response.json()
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert response.json()["attr"] == "evaluation_runtime"
            assert f"dependent (ID: {dependent.id})" in response.json()["detail"]

    @parameterized.expand(
        [
            ("unrelated_field", "server", True, lambda _: {"name": "Renamed"}),
            (
                "same_dependency_new_rollout",
                "server",
                True,
                lambda dep_id: {"filters": _depends_on(dep_id, rollout_percentage=50)},
            ),
            ("reenable", "server", False, lambda _: {"active": True}),
            ("unset_to_all", None, True, lambda _: {"evaluation_runtime": "all"}),
        ]
    )
    def test_existing_mismatched_dependency_does_not_block_other_edits(
        self, _name: str, dependent_runtime: str | None, dependent_active: bool, data_for: Callable[[int], dict]
    ) -> None:
        dependency = self._flag("dependency", "client")
        dependent = self._flag(
            "dependent", dependent_runtime, filters=_depends_on(dependency.id), active=dependent_active
        )

        response = self._patch(dependent, data_for(dependency.id))

        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_adding_a_mismatched_dependency_next_to_an_existing_one_is_rejected(self) -> None:
        old_dependency = self._flag("old_dependency", "client")
        new_dependency = self._flag("new_dependency", "client")
        dependent = self._flag("dependent", "server", filters=_depends_on(old_dependency.id))

        response = self._patch(dependent, {"filters": _depends_on(old_dependency.id, new_dependency.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert f"'new_dependency' (ID: {new_dependency.id})" in response.json()["detail"]
