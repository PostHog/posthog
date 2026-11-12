from uuid import UUID

from django.db import router

import structlog

from posthog.models import User

from ..models import UserInterfaceFragment

logger = structlog.get_logger(__name__)
BATCH_SIZE = 1000


def delete_orphaned_fragment_batch(after: UUID | None = None) -> UUID | None:
    # Both reads use writers: replica lag must never turn a live user into an orphan.
    fragments = UserInterfaceFragment.objects.unscoped().using(router.db_for_write(UserInterfaceFragment))
    candidates = fragments.filter(id__gt=after) if after is not None else fragments
    rows = list(candidates.order_by("id").values_list("id", "user_id")[:BATCH_SIZE])
    if not rows:
        return None

    existing_users = set(
        User.objects.using(router.db_for_write(User))
        .filter(id__in={user_id for _, user_id in rows})
        .values_list("id", flat=True)
    )
    orphan_ids = [fragment_id for fragment_id, user_id in rows if user_id not in existing_users]
    deleted, _ = fragments.filter(id__in=orphan_ids).delete()
    logger.info("ui_customization.orphan_cleanup_batch", inspected=len(rows), deleted=deleted)
    return rows[-1][0] if len(rows) == BATCH_SIZE else None


def delete_fragments_for_teams(team_ids: list[int]) -> None:
    UserInterfaceFragment.objects.unscoped().filter(team_id__in=team_ids).delete()
