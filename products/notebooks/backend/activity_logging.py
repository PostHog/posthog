"""Activity-log helper for Notebook changes.

Kept out of the API module so the notebooks AppConfig can use it in the file-system
delete/restore hooks it registers at ready() without importing the API module — whose
module-scope imports reach the kernel runtime and the tasks sandbox (modal SDK).
"""

from datetime import datetime
from typing import Optional

from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, log_activity
from posthog.models.user import User
from posthog.models.utils import UUIDT

from products.notebooks.backend.models import Notebook


def log_notebook_activity(
    activity: str,
    notebook: Notebook,
    organization_id: UUIDT,
    team_id: int,
    user: User,
    was_impersonated: bool,
    changes: Optional[list[Change]] = None,
    created_at: datetime | None = None,
) -> ActivityLog | None:
    short_id = str(notebook.short_id)
    log = log_activity(
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=notebook.short_id,
        scope="Notebook",
        activity=activity,
        detail=Detail(changes=changes, short_id=short_id, name=notebook.title),
    )
    if log is not None and created_at is not None:
        ActivityLog.objects.filter(pk=log.pk).update(created_at=created_at)
        log.created_at = created_at
    return log
