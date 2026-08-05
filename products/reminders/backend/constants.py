from django.apps import apps
from django.db import models

from posthog.session_recordings.models.session_recording import SessionRecording

from products.dashboards.backend.models.dashboard import Dashboard
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.models.insight import Insight
from products.surveys.backend.models import Survey

# resource_type -> (model, lookup_field, frontend_path_segment)
# lookup_field is the column used to match resource_id within the team.
# frontend_path_segment builds the notification deep link: /project/{project_id}/{segment}/{resource_id}
RESOURCE_MODELS: dict[str, tuple[type[models.Model], str, str]] = {
    "dashboard": (Dashboard, "pk", "dashboard"),
    "insight": (Insight, "short_id", "insights"),
    "experiment": (Experiment, "pk", "experiments"),
    "feature_flag": (FeatureFlag, "pk", "feature_flags"),
    "survey": (Survey, "pk", "surveys"),
    "notebook": (Notebook, "short_id", "notebooks"),
    "replay": (SessionRecording, "session_id", "replay"),
    "error_tracking": (apps.get_model("error_tracking", "ErrorTrackingIssue"), "pk", "error_tracking"),
}

RESOURCE_TYPES: tuple[str, ...] = tuple(RESOURCE_MODELS.keys())

# Max reminders a single user may have in the `active` status per team.
MAX_ACTIVE_REMINDERS_PER_USER = 50

# A schedule may fire at most this many times in any 24h window.
MAX_FIRES_PER_DAY = 4
