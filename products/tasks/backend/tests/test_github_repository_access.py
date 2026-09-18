from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import Integration

from products.tasks.backend.github_repository_access import select_integration_for_repository


def _integration(pk: int, account_name: str | None, cached_repositories: list[str] | None = None) -> Integration:
    return Integration(
        id=pk,
        kind="github",
        integration_id=str(pk),
        config={"account": {"name": account_name}} if account_name else {},
        repository_cache=[
            {"id": index, "name": full_name.split("/")[1], "full_name": full_name}
            for index, full_name in enumerate(cached_repositories or [])
        ],
    )


class TestSelectIntegrationForRepository(SimpleTestCase):
    @parameterized.expand(
        [
            ("owner_of_the_repository_wins", "acme/widgets", 2),
            ("owner_match_is_case_insensitive", "ACME/Widgets", 2),
            ("first_installation_when_the_owner_is_connected_once", "posthog/posthog", 1),
            ("first_installation_when_no_account_owns_the_repository", "other/thing", 1),
            ("first_installation_when_the_task_has_no_repository", None, 1),
        ]
    )
    def test_selection(self, _name: str, repository: str | None, expected_id: int) -> None:
        integrations = [_integration(1, "posthog"), _integration(2, "acme")]

        selected = select_integration_for_repository(integrations, repository)

        assert selected is not None
        self.assertEqual(selected.id, expected_id)

    def test_repository_cache_resolves_an_installation_with_no_account_name(self) -> None:
        integrations = [_integration(1, "posthog"), _integration(2, None, ["acme/widgets"])]

        selected = select_integration_for_repository(integrations, "acme/widgets")

        assert selected is not None
        self.assertEqual(selected.id, 2)

    def test_no_installations(self) -> None:
        self.assertIsNone(select_integration_for_repository([], "acme/widgets"))
