"""Record how a release file list job ended: a Prometheus count and one product analytics event."""

import structlog

from posthog.event_usage import groups
from posthog.models import Team
from posthog.ph_client import ph_background_capture

from products.error_tracking.backend.logic.repo_paths.metrics import record_job_outcome
from products.error_tracking.backend.logic.repo_paths.release_files import ReleaseFileListResult

logger = structlog.get_logger(__name__)

FILE_LIST_STORED_EVENT = "error_tracking_release_file_list_stored"
_PUBLIC_GIT_HOSTS = frozenset({"github.com", "gitlab.com"})


def report_finished_job(team_id: int, release_id: str, result: ReleaseFileListResult) -> None:
    record_job_outcome(result.outcome)
    try:
        _capture_finished_job(team_id, release_id, result)
    except Exception:
        # A reporting error must not fail the activity: its retry would find the stored list and
        # report the job a second time, as "exists".
        logger.exception("error_tracking_repo_paths_report_failed", team_id=team_id, release_id=release_id)


def _capture_finished_job(team_id: int, release_id: str, result: ReleaseFileListResult) -> None:
    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None:
        return
    repo = result.repo
    stored = result.stored
    ph_background_capture()(
        distinct_id=str(team.uuid),
        event=FILE_LIST_STORED_EVENT,
        properties={
            "success": result.outcome in ("written", "exists"),
            "outcome": result.outcome,
            "release_id": release_id,
            "commit_id": repo.commit if repo else None,
            "provider": result.provider,
            "self_hosted": repo.slug.host not in _PUBLIC_GIT_HOSTS if repo else None,
            "path_count": stored.path_count if stored else None,
            "stored_bytes": stored.stored_bytes if stored else None,
            "fetched_bytes": stored.fetched_bytes if stored else None,
            "fetch_seconds": stored.fetch_seconds if stored else None,
            "removed_lists": stored.removed_lists if stored else None,
        },
        groups=groups(team.organization, team),
    )
