import json
import hashlib
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import posthoganalytics

from posthog.models import Team
from posthog.models.scoping import with_team_scope

from products.canvas.backend import report_canvas as canvas_api
from products.signals.backend.artefact_schemas import ArtefactContentValidationError, parse_artefact_content
from products.signals.backend.implementation_pr import fetch_implementation_pr_urls_for_reports
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportCanvas
from products.signals.backend.report_generation.resolve_reviewers import (
    normalized_github_logins_from_suggested_reviewer_artefacts,
    resolve_org_github_login_to_users,
)
from products.signals.backend.sandbox import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_acting_user_id_for_team,
)
from products.tasks.backend.facade import api as tasks_facade

REPORT_CANVAS_FEATURE_FLAG = "signals-report-canvases"
REPORT_CANVAS_CHANNEL_NAME = "general"
_MAX_CONTEXT_ARTEFACTS = 16
_MAX_CONTEXT_SIGNALS = 8
_MAX_CONTEXT_STRING_LENGTH = 4_000


@dataclass(frozen=True, kw_only=True)
class ReportCanvasGeneration:
    canvas_id: UUID
    discussion_task_id: UUID
    generation_task_id: UUID | None
    generation_run_id: UUID | None
    fingerprint: str
    skipped: bool = False


def _fetch_report_signals(report: SignalReport) -> list[dict]:
    from products.signals.backend.temporal.signal_queries import (  # noqa: PLC0415 — avoids the Temporal registry cycle
        fetch_signals_for_report_sync,
    )

    return fetch_signals_for_report_sync(report.team, str(report.id))


def report_canvases_enabled(team: Team) -> bool:
    if settings.DEBUG:
        return True
    try:
        return bool(
            posthoganalytics.feature_enabled(
                REPORT_CANVAS_FEATURE_FLAG,
                str(team.organization_id),
                groups={"organization": str(team.organization_id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def _report_fingerprint(report: SignalReport) -> str:
    pr_url = fetch_implementation_pr_urls_for_reports([str(report.id)]).get(str(report.id))
    payload = json.dumps(
        {
            "title": report.title,
            "summary": report.summary,
            "error": report.error,
            "charts": report.charts,
            "pr_url": pr_url,
            "run_count": report.run_count,
            "artefacts": _report_artefact_context(report),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _reviewer_user_ids(report: SignalReport) -> set[int]:
    artefacts = list(
        report.artefacts.filter(type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS).order_by("-created_at")
    )
    logins = normalized_github_logins_from_suggested_reviewer_artefacts(artefacts)
    return {user.id for user in resolve_org_github_login_to_users(report.team_id, logins).values()}


def _bounded_context_value(value: object) -> object:
    if isinstance(value, str):
        return value[:_MAX_CONTEXT_STRING_LENGTH]
    if isinstance(value, list):
        return [_bounded_context_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {str(key): _bounded_context_value(item) for key, item in list(value.items())[:30]}
    return value


def _report_artefact_context(report: SignalReport) -> list[dict]:
    artefacts: list[dict] = []
    seen_status_types: set[str] = set()
    seen_signal_ids: set[str] = set()

    for row in report.artefacts.order_by("-created_at")[:100]:
        if row.type in SignalReportArtefact.STATUS_ARTEFACT_TYPES:
            if row.type in seen_status_types:
                continue
            seen_status_types.add(row.type)
        try:
            content = parse_artefact_content(row.type, row.content).model_dump(mode="json")
        except ArtefactContentValidationError:
            continue
        if row.type == SignalReportArtefact.ArtefactType.SIGNAL_FINDING:
            signal_id = str(content.get("signal_id") or "")
            if signal_id in seen_signal_ids:
                continue
            seen_signal_ids.add(signal_id)
        artefacts.append({"type": row.type, "content": _bounded_context_value(content)})
        if len(artefacts) >= _MAX_CONTEXT_ARTEFACTS:
            break
    return artefacts


def _generation_prompt(
    report: SignalReport,
    canvas_id: UUID,
    *,
    collaborative: bool,
    signals: list[dict],
    pr_url: str | None,
) -> str:
    save_instruction = (
        "Stage the complete result as a draft. Do not publish or replace the live head."
        if collaborative
        else "Publish the complete result as the live canvas."
    )
    context = {
        "report_id": str(report.id),
        "status": report.status,
        "title": report.title,
        "summary": report.summary,
        "pending_input_reason": report.error,
        "charts": report.charts,
        "implementation_pr_url": pr_url,
        "signals": _bounded_context_value(signals[:_MAX_CONTEXT_SIGNALS]),
        "artefacts": _report_artefact_context(report),
    }
    return f"""Build a useful report canvas for Signal report {report.id}.

Use the building-canvases skill. Update the existing canvas with id {canvas_id}; never create another canvas.
Make the canvas useful before anyone starts a conversation:
- Put the conclusion and why it matters above the fold.
- Lead with representative evidence. Link to the underlying PostHog or GitHub source when a real URL is available.
- Prefer a relevant chart, replay, or source-specific visualization over prose when the supplied data supports it.
- Show confidence, uncertainty, open questions, suggested reviewers, existing work, and PR state when present.
- End with one clear recommended next step.

The canvas is presentation, not a trusted action surface. Do not render controls that merely look clickable. A button or link is allowed only when it navigates to a real supplied URL; otherwise present the next step as plain text. Desktop provides agent, PR, and lifecycle actions outside the canvas.

If a PR exists, make review status and the PR the primary outcome. Use live PostHog data or report charts when the supplied query nodes support them.

{save_instruction} Poll the resulting build until it is ready or failed before finishing.

Report context:
{json.dumps(context, default=str)}
"""


@with_team_scope()
def ensure_and_start_report_canvas_generation(*, team_id: int, report_id: str) -> ReportCanvasGeneration | None:
    team = Team.objects.select_related("organization").get(id=team_id)
    if not report_canvases_enabled(team):
        return None

    report = SignalReport.objects.select_related("team").get(id=report_id, team_id=team_id)
    if report.status not in (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT):
        return None
    fingerprint = _report_fingerprint(report)
    signals = _fetch_report_signals(report)
    pr_url = fetch_implementation_pr_urls_for_reports([str(report.id)]).get(str(report.id))

    with transaction.atomic():
        report = SignalReport.objects.select_for_update().select_related("team").get(id=report_id, team_id=team_id)
        session = SignalReportCanvas.objects.filter(report=report, team_id=team_id).first()
        if session is None:
            channel = tasks_facade.resolve_channel(team_id, None, name=REPORT_CANVAS_CHANNEL_NAME, star=False)
            if channel is None:
                raise RuntimeError("Could not resolve the report canvas channel")
            discussion_task_id = tasks_facade.create_shared_channel_task_without_run(
                team_id=team_id,
                channel_id=channel.id,
                title=report.title or "Report",
                description=report.summary or "",
                origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
                signal_report_id=report.id,
            )
            canvas_id = canvas_api.create_report_canvas(
                team_id=team_id,
                channel_id=channel.id,
                name=report.title or "Report",
                discussion_task_id=discussion_task_id,
            )
            session = SignalReportCanvas.objects.create(
                team_id=team_id,
                report=report,
                canvas_id=canvas_id,
                discussion_task_id=discussion_task_id,
            )
            tasks_facade.set_task_activity_target(
                team_id=team_id,
                task_id=discussion_task_id,
                scope="desktop_canvas",
                target_id=canvas_id,
            )
        title = report.title or "Report"
        tasks_facade.update_shared_task_context(
            team_id=team_id,
            task_id=session.discussion_task_id,
            title=title,
            description=report.summary or "",
        )
        canvas_api.set_canvas_name(team_id=team_id, canvas_id=session.canvas_id, name=title)
        if (
            session.generated_fingerprint == fingerprint
            and session.generation_status == SignalReportCanvas.GenerationStatus.READY
        ):
            return ReportCanvasGeneration(
                canvas_id=session.canvas_id,
                discussion_task_id=session.discussion_task_id,
                generation_task_id=session.generation_task_id,
                generation_run_id=None,
                fingerprint=fingerprint,
                skipped=True,
            )
        if (
            session.generated_fingerprint == fingerprint
            and session.generation_status == SignalReportCanvas.GenerationStatus.GENERATING
            and session.generation_task_id is not None
        ):
            latest_run = tasks_facade.get_latest_run_by_task([session.generation_task_id]).get(
                str(session.generation_task_id)
            )
            return ReportCanvasGeneration(
                canvas_id=session.canvas_id,
                discussion_task_id=session.discussion_task_id,
                generation_task_id=session.generation_task_id,
                generation_run_id=latest_run.id if latest_run else None,
                fingerprint=fingerprint,
            )
        session.generation_status = SignalReportCanvas.GenerationStatus.GENERATING
        session.failure_reason = ""
        session.generated_fingerprint = fingerprint
        session.save(update_fields=["generation_status", "failure_reason", "generated_fingerprint", "updated_at"])

        user_id = resolve_acting_user_id_for_team(team_id)
        if user_id is None:
            raise RuntimeError("No active organization member can run the report canvas agent")
        sandbox_environment_id = get_or_create_signals_sandbox_env(
            team_id,
            SIGNALS_REPORT_RESEARCH_ENV_NAME,
            tasks_facade.SandboxNetworkAccessLevel.TRUSTED,
        )
        prompt = _generation_prompt(
            report,
            session.canvas_id,
            collaborative=session.collaboration_mode == SignalReportCanvas.CollaborationMode.COLLABORATIVE,
            signals=signals,
            pr_url=pr_url,
        )
        generation = tasks_facade.create_and_run_task(
            team=team,
            title=f"Canvas: {report.title or 'Report'}",
            description=prompt,
            origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
            user_id=user_id,
            create_pr=False,
            pending_user_message=prompt,
            posthog_mcp_scopes="report_canvas",
            signal_report_id=str(report.id),
            channel_id=canvas_api.get_canvas_channel_id(team_id=team_id, canvas_id=session.canvas_id),
            internal=True,
            sandbox_environment_id=sandbox_environment_id,
            interaction_origin="signal_report_canvas",
            ai_stage="report_canvas",
        )
        if generation.latest_run is None:
            raise RuntimeError("Report canvas generation did not create a run")
        canvas_api.set_generation_task(team_id=team_id, canvas_id=session.canvas_id, task_id=generation.task_id)
        session.generation_task_id = generation.task_id
        session.save(update_fields=["generation_task_id", "updated_at"])

    return ReportCanvasGeneration(
        canvas_id=session.canvas_id,
        discussion_task_id=session.discussion_task_id,
        generation_task_id=generation.task_id,
        generation_run_id=generation.latest_run.id,
        fingerprint=fingerprint,
    )


@with_team_scope()
def finalize_report_canvas_generation(
    *, team_id: int, report_id: str, generation: ReportCanvasGeneration, notify_reviewers: bool = True
) -> bool | None:
    if generation.skipped:
        return True
    if generation.generation_task_id is None or generation.generation_run_id is None:
        return False
    canvas_state = canvas_api.canvas_generation_result(
        team_id=team_id,
        canvas_id=generation.canvas_id,
        task_id=generation.generation_task_id,
    )
    if canvas_state.status in ("waiting_for_source", "building"):
        terminal = tasks_facade.task_run_is_terminal(
            generation.generation_run_id, generation.generation_task_id, team_id
        )
        if not terminal or canvas_state.status == "building":
            return None

    succeeded = canvas_state.status == "ready"
    session = SignalReportCanvas.objects.for_team(team_id).get(report_id=report_id)
    session.generation_status = (
        SignalReportCanvas.GenerationStatus.READY if succeeded else SignalReportCanvas.GenerationStatus.FAILED
    )
    session.failure_reason = (
        ""
        if succeeded
        else canvas_state.failure_reason or "The canvas agent finished without producing a canvas version."
    )
    if succeeded:
        session.generated_fingerprint = generation.fingerprint
    session.save(update_fields=["generation_status", "failure_reason", "generated_fingerprint", "updated_at"])
    if succeeded and notify_reviewers:
        report = SignalReport.objects.get(id=report_id, team_id=team_id)
        tasks_facade.record_task_activity_for_users(
            team_id=team_id,
            task_id=session.discussion_task_id,
            user_ids=_reviewer_user_ids(report),
            kind="completed",
        )
    return succeeded


@with_team_scope()
def fail_report_canvas_generation(*, team_id: int, report_id: str, generation_task_id: UUID) -> None:
    SignalReportCanvas.objects.for_team(team_id).filter(
        report_id=report_id,
        generation_task_id=generation_task_id,
        generation_status=SignalReportCanvas.GenerationStatus.GENERATING,
    ).update(
        generation_status=SignalReportCanvas.GenerationStatus.FAILED,
        failure_reason="Canvas generation timed out.",
        updated_at=timezone.now(),
    )
