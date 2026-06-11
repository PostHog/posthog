"""Activity-log helper for Notebook changes.

Kept out of the API module so the notebooks AppConfig can use it in the file-system
delete/restore hooks it registers at ready() without importing the API module — whose
module-scope imports reach the kernel runtime and the tasks sandbox (modal SDK).
"""

from typing import Optional

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
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
) -> None:
    short_id = str(notebook.short_id)
    log_activity(
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=notebook.short_id,
        scope="Notebook",
        activity=activity,
        detail=Detail(changes=changes, short_id=short_id, name=notebook.title),
    )
