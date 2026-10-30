from collections.abc import Callable

from django.apps import apps
from django.db import models

from posthog.session_recordings.models.session_recording import SessionRecording

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.dashboards.backend.models.dashboard import Dashboard
from products.experiments.backend.facade import reminders as experiments_reminders
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight
from products.surveys.backend.models import Survey

FacadeLookup = Callable[[int, str], ObjectAccessRef | None]


def _find_experiment(team_id: int, resource_id: str) -> ObjectAccessRef | None:
    experiment = experiments_reminders.get_experiment_ref(team_id=team_id, experiment_id=int(resource_id))
    if experiment is None:
        return None
    return ObjectAccessRef(
        resource="experiment",
        id=str(experiment.id),
        team_id=experiment.team_id,
        created_by_id=experiment.created_by_id,
    )


# resource_type -> (lookup, frontend_path_segment)
# lookup is a model and the column used to match resource_id within the team. A resource whose model stays
# behind its product's facade has a function instead, which returns the resource's access reference.
# frontend_path_segment builds the notification deep link: /project/{project_id}/{segment}/{resource_id}
RESOURCE_LOOKUPS: dict[str, tuple[tuple[type[models.Model], str] | FacadeLookup, str]] = {
    "dashboard": ((Dashboard, "pk"), "dashboard"),
    "insight": ((Insight, "short_id"), "insights"),
    "experiment": (_find_experiment, "experiments"),
    "feature_flag": ((FeatureFlag, "pk"), "feature_flags"),
    "survey": ((Survey, "pk"), "surveys"),
    "notebook": ((Notebook, "short_id"), "notebooks"),
    "replay": ((SessionRecording, "session_id"), "replay"),
    "error_tracking": ((apps.get_model("error_tracking", "ErrorTrackingIssue"), "pk"), "error_tracking"),
}

RESOURCE_TYPES: tuple[str, ...] = tuple(RESOURCE_LOOKUPS.keys())

# Max reminders a single user may have in the `active` status per team.
MAX_ACTIVE_REMINDERS_PER_USER = 50

# A schedule may fire at most this many times in any 24h window.
MAX_FIRES_PER_DAY = 4
