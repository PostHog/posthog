from datetime import timedelta

import pytest

from django.utils import timezone

from products.tasks.backend.logic.services.publication_policy import (
    PublicationPolicyError,
    validate_publication_metadata,
)


def test_policy_rejects_a_non_server_owned_branch_and_expired_window() -> None:
    with pytest.raises(PublicationPolicyError):
        validate_publication_metadata(
            head_branch="main",
            starts_before=timezone.now() - timedelta(minutes=2),
            expires_at=timezone.now() - timedelta(minutes=1),
        )


def test_starts_before_is_the_latest_allowed_start() -> None:
    validate_publication_metadata(
        head_branch="codex/tasks-draft-0123456789abcdef0123456789abcdef",
        starts_before=timezone.now() + timedelta(minutes=1),
        expires_at=timezone.now() + timedelta(minutes=2),
    )

    with pytest.raises(PublicationPolicyError):
        validate_publication_metadata(
            head_branch="codex/tasks-draft-0123456789abcdef0123456789abcdef",
            starts_before=timezone.now() - timedelta(seconds=1),
            expires_at=timezone.now() + timedelta(minutes=2),
        )

    validate_publication_metadata(
        head_branch="codex/tasks-draft-0123456789abcdef0123456789abcdef",
        starts_before=timezone.now() - timedelta(seconds=1),
        expires_at=timezone.now() + timedelta(minutes=2),
        already_started=True,
    )
