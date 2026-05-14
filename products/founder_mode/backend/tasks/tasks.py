"""Celery tasks for founder_mode.

One task per stage that needs LLM work:
- `run_validation_task` (stage 2) — two-pass Gemini with grounded search → `validation`
- `run_gtm_task` (stage 3) — single Gemini call, conceptual positioning + pricing → `gtm`
- `run_mvp_task` (stage 4) — single Gemini call, MVP happy path (placeholder prompt) → `mvp`
- `run_landing_page_task` (stage 5a) — single Gemini call, landing page build spec → `marketing_page`
- `run_practical_steps_task` (stage 5b) — single OpenAI call, launch playbook → `marketing_steps`

All tasks share the same shape: write a `running` envelope → call the service → write
`completed` or `failed` back to the stage's JSON column. Tasks are the sole writers to
their respective columns during a run.

Architectural note: skipping the facade for now since no other product consumes founder_mode.
Tasks call logic/ directly. Reintroduce a facade once a cross-product consumer appears.
"""

from datetime import UTC, datetime

import structlog
from celery import shared_task

from posthog.models.user import User

from products.founder_mode.backend.logic.gtm.service import generate_gtm_summary
from products.founder_mode.backend.logic.hashing import ideation_hash
from products.founder_mode.backend.logic.landing_page.service import generate_landing_page
from products.founder_mode.backend.logic.mvp.service import generate_mvp_happy_path
from products.founder_mode.backend.logic.practical_steps.service import generate_practical_steps
from products.founder_mode.backend.logic.validation.service import run_validation
from products.founder_mode.backend.models import FounderProject

logger = structlog.get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --- Validation (stage 2) ---


@shared_task(ignore_result=True)
def run_validation_task(founder_project_id: str, user_id: int | None = None) -> None:
    """Run the validation flow for a FounderProject and write the result back to its `validation` JSON.

    Writes `current_pass` between Gemini calls so the frontend can render real staged
    progress instead of estimating from elapsed time.
    """
    project = FounderProject.objects.select_related("team").get(id=founder_project_id)

    if not project.ideation:
        logger.warning("Skipping validation, no ideation set", project_id=founder_project_id)
        return

    user = User.objects.filter(id=user_id).first() if user_id else project.created_by
    if user is None:
        logger.warning("No user to run validation as", project_id=founder_project_id)
        return

    snapshot_hash = ideation_hash(project.ideation)
    started_at = _now_iso()

    project.validation = {
        "status": "running",
        "current_pass": "research",
        "started_at": started_at,
        "ideation_hash": snapshot_hash,
        "report": None,
        "trace_id": None,
        "error": "",
    }
    project.save(update_fields=["validation", "updated_at"])

    def on_pass_change(pass_name: str) -> None:
        # Patch only `current_pass` — the surrounding envelope (started_at, status, hash) is
        # immutable for the duration of this task, so we splat to preserve it.
        project.validation = {**project.validation, "current_pass": pass_name}
        project.save(update_fields=["validation", "updated_at"])

    try:
        report, trace_id = run_validation(
            ideation_payload=project.ideation,
            team=project.team,
            user=user,
            on_pass_change=on_pass_change,
        )
    except Exception as exc:
        logger.exception("Validation run failed", project_id=founder_project_id)
        project.validation = {
            "status": "failed",
            "started_at": started_at,
            "failed_at": _now_iso(),
            "ideation_hash": snapshot_hash,
            "report": None,
            "trace_id": None,
            "error": str(exc),
        }
        project.save(update_fields=["validation", "updated_at"])
        return

    project.validation = {
        "status": "completed",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "ideation_hash": snapshot_hash,
        "report": report.model_dump(),
        "trace_id": trace_id,
        "error": "",
    }
    project.save(update_fields=["validation", "updated_at"])


# --- Conceptual GTM (stage 3) ---


@shared_task(ignore_result=True)
def run_gtm_task(founder_project_id: str, user_id: int | None = None) -> None:
    """Generate the conceptual GTM summary (positioning, pricing, channels) → `gtm` column."""
    project = FounderProject.objects.select_related("team").get(id=founder_project_id)

    if not project.ideation:
        logger.warning("Skipping GTM, no ideation set", project_id=founder_project_id)
        return

    user = User.objects.filter(id=user_id).first() if user_id else project.created_by
    if user is None:
        logger.warning("No user to run GTM as", project_id=founder_project_id)
        return

    started_at = _now_iso()
    project.gtm = {
        "status": "running",
        "started_at": started_at,
        "result": None,
        "trace_id": None,
        "error": "",
    }
    project.save(update_fields=["gtm", "updated_at"])

    try:
        summary, trace_id = generate_gtm_summary(
            ideation=project.ideation,
            validation=project.validation or {},
            team=project.team,
            user=user,
        )
    except Exception as exc:
        logger.exception("GTM run failed", project_id=founder_project_id)
        project.gtm = {
            "status": "failed",
            "started_at": started_at,
            "failed_at": _now_iso(),
            "result": None,
            "trace_id": None,
            "error": str(exc),
        }
        project.save(update_fields=["gtm", "updated_at"])
        return

    project.gtm = {
        "status": "completed",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "result": summary.model_dump(),
        "trace_id": trace_id,
        "error": "",
    }
    project.save(update_fields=["gtm", "updated_at"])


# --- MVP happy path (stage 4) ---


@shared_task(ignore_result=True)
def run_mvp_task(founder_project_id: str, user_id: int | None = None) -> None:
    """Generate the MVP happy-path spec → `mvp` column.

    Placeholder prompt — content shape still in flux. See logic/mvp/service.py.
    """
    project = FounderProject.objects.select_related("team").get(id=founder_project_id)

    if not project.ideation:
        logger.warning("Skipping MVP, no ideation set", project_id=founder_project_id)
        return

    user = User.objects.filter(id=user_id).first() if user_id else project.created_by
    if user is None:
        logger.warning("No user to run MVP as", project_id=founder_project_id)
        return

    started_at = _now_iso()
    project.mvp = {
        "status": "running",
        "started_at": started_at,
        "result": None,
        "trace_id": None,
        "error": "",
    }
    project.save(update_fields=["mvp", "updated_at"])

    try:
        spec, trace_id = generate_mvp_happy_path(
            ideation=project.ideation,
            validation=project.validation or {},
            gtm=project.gtm or {},
            team=project.team,
            user=user,
        )
    except Exception as exc:
        logger.exception("MVP run failed", project_id=founder_project_id)
        project.mvp = {
            "status": "failed",
            "started_at": started_at,
            "failed_at": _now_iso(),
            "result": None,
            "trace_id": None,
            "error": str(exc),
        }
        project.save(update_fields=["mvp", "updated_at"])
        return

    project.mvp = {
        "status": "completed",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "result": spec.model_dump(),
        "trace_id": trace_id,
        "error": "",
    }
    project.save(update_fields=["mvp", "updated_at"])


# --- Marketing: landing page build spec (stage 5a) ---


@shared_task(ignore_result=True)
def run_landing_page_task(founder_project_id: str, user_id: int | None = None) -> None:
    """Generate a landing page build spec → `marketing_page` column."""
    project = FounderProject.objects.select_related("team").get(id=founder_project_id)

    if not project.ideation:
        logger.warning("Skipping landing page, no ideation set", project_id=founder_project_id)
        return

    user = User.objects.filter(id=user_id).first() if user_id else project.created_by
    if user is None:
        logger.warning("No user to generate landing page as", project_id=founder_project_id)
        return

    started_at = _now_iso()
    project.marketing_page = {
        "status": "running",
        "started_at": started_at,
        "page": None,
        "trace_id": None,
        "error": "",
    }
    project.save(update_fields=["marketing_page", "updated_at"])

    try:
        page, trace_id = generate_landing_page(
            project_name=project.name,
            ideation=project.ideation,
            validation=project.validation or {},
            gtm=project.gtm or {},
            mvp=project.mvp or {},
            team=project.team,
            user=user,
        )
    except Exception as exc:
        logger.exception("Landing page generation failed", project_id=founder_project_id)
        project.marketing_page = {
            "status": "failed",
            "started_at": started_at,
            "failed_at": _now_iso(),
            "page": None,
            "trace_id": None,
            "error": str(exc),
        }
        project.save(update_fields=["marketing_page", "updated_at"])
        return

    project.marketing_page = {
        "status": "completed",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "page": page.model_dump(),
        "trace_id": trace_id,
        "error": "",
    }
    project.save(update_fields=["marketing_page", "updated_at"])


# --- Marketing: practical launch playbook (stage 5b) ---


@shared_task(ignore_result=True)
def run_practical_steps_task(founder_project_id: str, user_id: int | None = None) -> None:
    """Generate the practical launch playbook → `marketing_steps` column.

    Replaces the old standalone `run_gtm_task` (OpenAI launch-playbook generator). Reads
    project state instead of taking a fresh `product_description`.
    """
    project = FounderProject.objects.select_related("team").get(id=founder_project_id)

    if not project.ideation:
        logger.warning("Skipping practical steps, no ideation set", project_id=founder_project_id)
        return

    user = User.objects.filter(id=user_id).first() if user_id else project.created_by
    if user is None:
        logger.warning("No user to generate practical steps as", project_id=founder_project_id)
        return

    started_at = _now_iso()
    project.marketing_steps = {
        "status": "running",
        "started_at": started_at,
        "result": None,
        "trace_id": None,
        "error": "",
    }
    project.save(update_fields=["marketing_steps", "updated_at"])

    try:
        result, trace_id = generate_practical_steps(
            ideation=project.ideation,
            validation=project.validation or {},
            gtm=project.gtm or {},
            mvp=project.mvp or {},
            team=project.team,
            user=user,
        )
    except Exception as exc:
        logger.exception("Practical steps generation failed", project_id=founder_project_id)
        project.marketing_steps = {
            "status": "failed",
            "started_at": started_at,
            "failed_at": _now_iso(),
            "result": None,
            "trace_id": None,
            "error": str(exc),
        }
        project.save(update_fields=["marketing_steps", "updated_at"])
        return

    project.marketing_steps = {
        "status": "completed",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "result": result.model_dump(),
        "trace_id": trace_id,
        "error": "",
    }
    project.save(update_fields=["marketing_steps", "updated_at"])
