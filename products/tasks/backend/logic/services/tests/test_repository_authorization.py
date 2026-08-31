from django.test import override_settings

from products.tasks.backend.logic.services.repository_authorization import (
    _writable_repositories,
    repository_is_authorizable,
)


@override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=[])
def test_writable_repository_filter_rejects_public_repositories_without_an_allowlist_entry() -> None:
    repositories = _writable_repositories(
        [
            {
                "full_name": "owner/public-repo",
                "can_push": True,
                "private": False,
                "visibility": "public",
            }
        ]
    )

    assert repositories == {}


@override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=[])
def test_writable_repository_filter_keeps_private_repositories() -> None:
    repositories = _writable_repositories(
        [
            {
                "full_name": "owner/private-repo",
                "can_push": True,
                "private": True,
                "visibility": "private",
            }
        ]
    )

    assert repositories == {"owner/private-repo": "owner/private-repo"}


@override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=[])
def test_writable_repository_filter_rejects_repositories_without_visibility_metadata() -> None:
    repositories = _writable_repositories(
        [
            {
                "full_name": "owner/unknown-repo",
                "can_push": True,
            }
        ]
    )

    assert repositories == {}


@override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=["OWNER/PUBLIC-REPO"])
def test_writable_repository_filter_normalizes_the_public_allowlist() -> None:
    repositories = _writable_repositories(
        [
            {
                "full_name": "owner/public-repo",
                "can_push": True,
                "private": False,
                "visibility": "public",
            }
        ]
    )

    assert repositories == {"owner/public-repo": "owner/public-repo"}


@override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=[])
def test_staged_grant_revalidation_uses_the_same_public_repository_filter() -> None:
    assert not repository_is_authorizable(
        [
            {
                "full_name": "owner/public-repo",
                "can_push": True,
                "private": False,
                "visibility": "public",
            }
        ],
        "OWNER/PUBLIC-REPO",
    )
