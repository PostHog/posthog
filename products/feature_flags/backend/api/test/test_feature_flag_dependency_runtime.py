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
            assert f"Cannot depend on flag (ID: {dependency.id})" in response.json()["detail"]
            assert "'dependency'" not in response.json()["detail"]

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
        self._flag("dependent", "server", filters=_depends_on(dependency.id), active=dependent_active)

        response = self._patch(dependency, {"evaluation_runtime": new_runtime})

        if allowed:
            assert response.status_code == status.HTTP_200_OK, response.json()
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert response.json()["attr"] == "evaluation_runtime"
            assert "dependent" not in response.json()["detail"]
            assert "1 flag(s)" in response.json()["detail"]

    @parameterized.expand(
        [
            ("null_properties", {"groups": [{"properties": None, "rollout_percentage": 100}]}),
            ("scalar_groups", {"groups": "all"}),
            ("null_groups", {"groups": None}),
        ]
    )
    def test_changing_runtime_tolerates_unrelated_flag_with_legacy_filters(self, _name: str, filters: dict) -> None:
        flag = self._flag("flag", "all")
        self._flag("legacy", "all", filters=filters)

        response = self._patch(flag, {"evaluation_runtime": "client"})

        assert response.status_code == status.HTTP_200_OK, response.json()

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

    def _enable_object_access_controls(self) -> None:
        from posthog.constants import AvailableFeature

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

    def test_unreadable_dependency_looks_like_a_missing_flag(self) -> None:
        from posthog.models.organization import OrganizationMembership

        from products.access_control.backend.models.access_control import AccessControl

        self._enable_object_access_controls()
        secret = self._flag("secret_dependency", "client")
        AccessControl.objects.create(
            resource="feature_flag", resource_id=secret.id, team=self.team, access_level="none"
        )
        missing_id = secret.id + 1000
        self.client.force_login(self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER))
        dependent = self._flag("dependent", "server")

        hidden = self._patch(dependent, {"filters": _depends_on(secret.id)})
        absent = self._patch(dependent, {"filters": _depends_on(missing_id)})

        assert hidden.status_code == absent.status_code == status.HTTP_400_BAD_REQUEST, (hidden.json(), absent.json())
        assert hidden.json()["detail"] == f"Flag dependency references non-existent flag with ID {secret.id}"
        assert absent.json()["detail"] == f"Flag dependency references non-existent flag with ID {missing_id}"
        assert "secret_dependency" not in str(hidden.json())
        for key in ("type", "code", "attr"):
            assert hidden.json()[key] == absent.json()[key]

    def test_unreadable_disabled_dependency_is_reported_as_missing(self) -> None:
        from posthog.models.organization import OrganizationMembership

        from products.access_control.backend.models.access_control import AccessControl

        self._enable_object_access_controls()
        disabled = self._flag("hidden_disabled", "all", active=False)
        AccessControl.objects.create(
            resource="feature_flag", resource_id=disabled.id, team=self.team, access_level="none"
        )
        self.client.force_login(self._create_user("member2@posthog.com", level=OrganizationMembership.Level.MEMBER))
        dependent = self._flag("dependent_on_disabled", "all")

        response = self._patch(dependent, {"filters": _depends_on(disabled.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == f"Flag dependency references non-existent flag with ID {disabled.id}"
        assert "hidden_disabled" not in str(response.json())

    def _hidden_flag_as_member(self, key: str, runtime: str) -> FeatureFlag:
        from posthog.models.organization import OrganizationMembership

        from products.access_control.backend.models.access_control import AccessControl

        self._enable_object_access_controls()
        hidden = self._flag(key, runtime)
        AccessControl.objects.create(
            resource="feature_flag", resource_id=hidden.id, team=self.team, access_level="none"
        )
        self.client.force_login(self._create_user(f"{key}@posthog.com", level=OrganizationMembership.Level.MEMBER))
        return hidden

    @parameterized.expand(
        [("rollout_edit_over_stored_dependency", False), ("adding_a_readable_flag_that_depends_on_it", True)]
    )
    def test_unreadable_dependency_the_write_does_not_add_does_not_block_edits(
        self, _name: str, through_readable_flag: bool
    ) -> None:
        hidden = self._hidden_flag_as_member("hidden_dependency", "all")
        if through_readable_flag:
            middle = self._flag("readable_middle", "all", filters=_depends_on(hidden.id))
            dependent = self._flag("dependent", "server")
            data = {"filters": _depends_on(middle.id)}
        else:
            dependent = self._flag("dependent", "server", filters=_depends_on(hidden.id))
            data = {"filters": _depends_on(hidden.id, rollout_percentage=50)}

        response = self._patch(dependent, data)

        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_runtime_change_over_unreadable_stored_dependency_looks_like_a_missing_flag(self) -> None:
        hidden = self._hidden_flag_as_member("hidden_client_dependency", "client")
        dependent = self._flag("dependent", "client", filters=_depends_on(hidden.id))

        response = self._patch(dependent, {"evaluation_runtime": "server"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == f"Flag dependency references non-existent flag with ID {hidden.id}"
        assert "hidden_client_dependency" not in str(response.json())
        dependent.refresh_from_db()
        assert dependent.evaluation_runtime == "client"

    def test_stored_disabled_hidden_dependency_reveals_nothing_on_an_edit(self) -> None:
        hidden = self._hidden_flag_as_member("hidden_disabled_dependency", "all")
        hidden.active = False
        hidden.save()
        dependent = self._flag("dependent_on_hidden", "all", filters=_depends_on(hidden.id))

        response = self._patch(dependent, {"filters": _depends_on(hidden.id, rollout_percentage=50)})

        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_runtime_change_ignores_a_dependent_the_caller_cannot_read(self) -> None:
        dependent = self._hidden_flag_as_member("hidden_dependent", "server")
        dependent.filters = _depends_on(self._flag("target", "client").id)
        dependent.save()
        target = FeatureFlag.objects.get(key="target", team=self.team)

        response = self._patch(target, {"evaluation_runtime": "server"})

        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_readable_dependency_shows_its_runtime_to_a_member(self) -> None:
        from posthog.models.organization import OrganizationMembership

        self._enable_object_access_controls()
        dependency = self._flag("dependency", "client")
        self.client.force_login(self._create_user("member3@posthog.com", level=OrganizationMembership.Level.MEMBER))
        dependent = self._flag("dependent", "server")

        response = self._patch(dependent, {"filters": _depends_on(dependency.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "client-side only" in response.json()["detail"]

    def test_adding_a_mismatched_dependency_next_to_an_existing_one_is_rejected(self) -> None:
        old_dependency = self._flag("old_dependency", "client")
        new_dependency = self._flag("new_dependency", "client")
        dependent = self._flag("dependent", "server", filters=_depends_on(old_dependency.id))

        response = self._patch(dependent, {"filters": _depends_on(old_dependency.id, new_dependency.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert f"Cannot depend on flag (ID: {new_dependency.id})" in response.json()["detail"]
        assert "new_dependency" not in response.json()["detail"]
