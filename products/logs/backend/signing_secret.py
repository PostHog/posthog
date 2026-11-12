from __future__ import annotations

from dataclasses import field
from datetime import UTC, datetime

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token, mask_key_value

from products.logs.backend.models import LogsSigningSecret


@frozen
class SigningSecretState:
    # repr=False keeps the raw secret out of logs and tracebacks.
    secret: str | None = field(repr=False)
    updated_at: datetime | None
    previous_secret_valid_until: datetime | None


def _state(row: LogsSigningSecret | None) -> SigningSecretState:
    return SigningSecretState(
        secret=row.secret if row else None,
        updated_at=row.updated_at if row else None,
        previous_secret_valid_until=row.previous_secret_valid_until if row and row.previous_secret_active else None,
    )


def _log_change(team: Team, user: User, was_impersonated: bool, change: Change) -> None:
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=user,
        was_impersonated=was_impersonated,
        scope="Team",
        item_id=team.id,
        activity="updated",
        detail=Detail(name=str(team.name), changes=[change]),
        # Without strict, the audit insert runs after the commit and a failure there is swallowed.
        strict=True,
    )


def get_signing_secret(team: Team) -> SigningSecretState:
    return _state(LogsSigningSecret.objects.for_team(team.id).first())


def rotate_signing_secret(team: Team, user: User, was_impersonated: bool) -> SigningSecretState:
    # One transaction, because a credential change must not commit without its audit row.
    with transaction.atomic():
        # The row lock makes two concurrent requests run one after the other. Without it,
        # the second request overwrites the secret that the first request just returned.
        row, created = (
            LogsSigningSecret.objects.for_team(team.id)
            .select_for_update()
            .get_or_create(team_id=team.id, defaults={"secret": generate_random_token()})
        )
        old_secret = None if created else row.secret
        if not created:
            row.previous_secret = row.secret
            row.previous_secret_rotated_at = datetime.now(UTC)
            row.secret = generate_random_token()
            row.save()
        _log_change(
            team,
            user,
            was_impersonated,
            Change(
                type="Team",
                action="created" if created else "changed",
                field="logs_signing_secret",
                before=mask_key_value(old_secret) if old_secret else None,
                after=mask_key_value(row.secret),
            ),
        )
    return _state(row)


def expire_previous_signing_secret(team: Team, user: User, was_impersonated: bool) -> SigningSecretState:
    with transaction.atomic():
        row = LogsSigningSecret.objects.for_team(team.id).select_for_update().first()
        if row and row.previous_secret:
            expired = row.previous_secret
            row.previous_secret = None
            row.previous_secret_rotated_at = None
            row.save(update_fields=["previous_secret", "previous_secret_rotated_at", "updated_at"])
            _log_change(
                team,
                user,
                was_impersonated,
                Change(
                    type="Team",
                    action="deleted",
                    field="logs_signing_secret_previous",
                    before=mask_key_value(expired),
                    after=None,
                ),
            )
    return _state(row)
