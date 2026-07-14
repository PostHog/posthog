"""Post-onboarding setup audit: proposal reports for the inbox cold start.

Runs after a team's wizard instrumentation PR merges. Deterministic checks find which PostHog
capabilities the team's setup is missing (custom events, feature flags, error tracking, logs),
one LLM call personalizes the pitch, and each gap becomes a `SignalReport` carrying a `proposal`
artefact plus a preset `repo_selection`. Proposal reports are never auto-started — the inbox
renders them when it would otherwise be empty, and approving one kicks off the regular
implementation-task flow.
"""

import json
from dataclasses import dataclass
from datetime import timedelta

import structlog
import posthoganalytics
from pydantic import BaseModel, Field
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

logger = structlog.get_logger(__name__)

SETUP_AUDIT_CATEGORIES = ("events", "feature_flags", "error_tracking", "logs")

# Category -> the PostHog product the proposed PR sets up.
CATEGORY_PRODUCTS: dict[str, str] = {
    "events": "product_analytics",
    "feature_flags": "feature_flags",
    "error_tracking": "error_tracking",
    "logs": "logs",
}

# Deterministic fallback copy, used verbatim when the personalization LLM call fails. The
# `{repository}` placeholder is filled in by `_fallback_copy`.
FALLBACK_COPY: dict[str, tuple[str, str]] = {
    "events": (
        "Instrument your key product events",
        "Your project only captures autocaptured events so far, so PostHog can't tell signups from "
        "bounces. This PR would instrument the core actions of {repository} as named events and "
        "create your first conversion funnel from them.",
    ),
    "feature_flags": (
        "Ship your next change behind a feature flag",
        "No feature flags are active in this project yet. This PR would wire the PostHog flags SDK "
        "into {repository} and gate one real code path behind a flag, so you can roll out gradually "
        "and kill features without redeploying.",
    ),
    "error_tracking": (
        "Set up error tracking",
        "PostHog hasn't seen any exceptions from this project, which usually means error tracking "
        "isn't set up. This PR would enable exception capture in {repository} so errors land in "
        "PostHog with stack traces, grouped into issues.",
    ),
    "logs": (
        "Send your application logs to PostHog",
        "This project isn't shipping logs to PostHog yet. This PR would hook the logging setup of "
        "{repository} into PostHog Logs, so you can search and correlate logs with the events and "
        "sessions you already capture.",
    ),
}

PERSONALIZE_SYSTEM_PROMPT = """\
You write short pitches for proposed pull requests that improve a team's PostHog setup.

You get the team's context (repository, product/team name, what events they already capture) and a
list of detected setup gaps with evidence. For EACH gap, write:
- "title": max 70 chars, imperative, names the concrete improvement (it is a report title in an inbox).
- "summary": 2-3 sentences. First: what we noticed about THEIR setup (ground it in the evidence and
  their event names — never invent data). Then: what the proposed PR would do in their repository,
  concrete enough that an engineer could scope it. Mention the PostHog capability it unlocks.

Style: plain language, sentence case, no marketing fluff, no exclamation marks, no em dashes.
Write like a helpful engineer, not an ad.

Respond with JSON only:
{"proposals": [{"category": "<category>", "title": "...", "summary": "..."}, ...]}
Include every category you were given, exactly once, and no others.\
"""


@dataclass
class SetupAuditInputs:
    team_id: int
    repository: str


@dataclass
class SetupGap:
    category: str
    evidence: str


@dataclass
class DetectedGaps:
    gaps: list[SetupGap]
    # Context handed to the personalization prompt (team name, known event names, ...).
    team_name: str
    event_names: list[str]


@dataclass
class ProposalCopy:
    category: str
    title: str
    summary: str


@dataclass
class PersonalizeInputs:
    team_id: int
    repository: str
    detected: DetectedGaps


@dataclass
class CreateProposalsInputs:
    team_id: int
    repository: str
    proposals: list[ProposalCopy]


class _ProposalCopyItem(BaseModel):
    category: str
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1)


class _ProposalCopyResponse(BaseModel):
    proposals: list[_ProposalCopyItem]


def _fallback_copy(category: str, repository: str) -> ProposalCopy:
    title, summary = FALLBACK_COPY[category]
    return ProposalCopy(category=category, title=title, summary=summary.format(repository=repository))


@activity.defn
@scoped_temporal()
@close_db_connections
async def detect_setup_gaps_activity(inputs: SetupAuditInputs) -> DetectedGaps:
    """Deterministic per-team checks: which PostHog capabilities is this setup missing?"""
    from posthog.models import EventDefinition, Team
    from posthog.sync import database_sync_to_async

    from products.feature_flags.backend.models.feature_flag import FeatureFlag
    from products.signals.backend.models import SignalReportArtefact

    def _detect() -> DetectedGaps:
        team = Team.objects.get(id=inputs.team_id)

        # Idempotency backstop (the workflow id also dedupes): a team that already has proposal
        # reports was audited before — don't stack a second batch.
        if SignalReportArtefact.objects.filter(
            team_id=inputs.team_id, type=SignalReportArtefact.ArtefactType.PROPOSAL
        ).exists():
            return DetectedGaps(gaps=[], team_name=team.name, event_names=[])

        event_names = list(
            EventDefinition.objects.filter(team_id=inputs.team_id).order_by("name").values_list("name", flat=True)[:50]
        )
        custom_events = [name for name in event_names if not name.startswith("$")]

        gaps: list[SetupGap] = []

        if not custom_events:
            gaps.append(
                SetupGap(
                    category="events",
                    evidence=(
                        f"The project has {len(event_names)} event definitions, all autocaptured "
                        f"($-prefixed) - no custom product events are instrumented."
                    ),
                )
            )

        if not FeatureFlag.objects.filter(team_id=inputs.team_id, deleted=False, active=True).exists():
            gaps.append(SetupGap(category="feature_flags", evidence="The project has no active feature flags."))

        has_exceptions = (
            "$exception" in event_names
            or EventDefinition.objects.filter(team_id=inputs.team_id, name="$exception").exists()
        )
        if not has_exceptions and not team.autocapture_exceptions_opt_in:
            gaps.append(
                SetupGap(
                    category="error_tracking",
                    evidence=(
                        "No $exception events have been captured and exception autocapture is not "
                        "enabled - error tracking is not set up."
                    ),
                )
            )

        onboarded = team.has_completed_onboarding_for if isinstance(team.has_completed_onboarding_for, dict) else {}
        if not bool(onboarded.get("logs")):
            gaps.append(SetupGap(category="logs", evidence="The team has not set up the logs product."))

        return DetectedGaps(gaps=gaps, team_name=team.name, event_names=event_names[:20])

    return await database_sync_to_async(_detect, thread_sensitive=False)()


@activity.defn
@scoped_temporal()
@close_db_connections
async def personalize_proposals_activity(inputs: PersonalizeInputs) -> list[ProposalCopy]:
    """One LLM call to personalize all proposal pitches; templated copy on any failure."""
    from products.signals.backend.temporal.llm import call_llm

    detected = inputs.detected
    categories = [gap.category for gap in detected.gaps]
    if not categories:
        return []

    user_prompt = json.dumps(
        {
            "repository": inputs.repository,
            "team_name": detected.team_name,
            "captured_event_names": detected.event_names,
            "gaps": [{"category": gap.category, "evidence": gap.evidence} for gap in detected.gaps],
        },
        indent=2,
    )

    def validate(text: str) -> _ProposalCopyResponse:
        return _ProposalCopyResponse.model_validate(json.loads(text))

    try:
        response = await call_llm(
            team_id=inputs.team_id,
            system_prompt=PERSONALIZE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            validate=validate,
            stage="setup_audit_personalize",
        )
        by_category = {item.category: item for item in response.proposals}
    except Exception:
        logger.warning("setup audit personalization failed, using fallback copy", team_id=inputs.team_id)
        by_category = {}

    # The LLM output is best-effort garnish: any category it dropped or mangled falls back to the
    # deterministic template so a detected gap always produces a proposal.
    proposals: list[ProposalCopy] = []
    for category in categories:
        item = by_category.get(category)
        if item is None:
            proposals.append(_fallback_copy(category, inputs.repository))
        else:
            proposals.append(ProposalCopy(category=category, title=item.title, summary=item.summary))
    return proposals


@activity.defn
@scoped_temporal()
@close_db_connections
async def create_proposal_reports_activity(inputs: CreateProposalsInputs) -> list[str]:
    """Create one READY SignalReport per proposal, with `proposal` + `repo_selection` artefacts.

    Never triggers auto-start: proposals are approval-first by design, so both status artefacts
    are appended with ``reevaluate_autostart=False``.
    """
    from django.db import transaction

    from posthog.sync import database_sync_to_async

    from products.signals.backend.artefact_attribution import ArtefactAttribution
    from products.signals.backend.artefact_schemas import SetupProposal
    from products.signals.backend.models import SignalReport, SignalReportArtefact
    from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult

    def _create() -> list[str]:
        report_ids: list[str] = []
        attribution = ArtefactAttribution.system()
        for proposal in inputs.proposals:
            if proposal.category not in CATEGORY_PRODUCTS:
                logger.warning(
                    "setup audit skipped unknown proposal category",
                    team_id=inputs.team_id,
                    category=proposal.category,
                )
                continue
            with transaction.atomic():
                report = SignalReport.objects.create(
                    team_id=inputs.team_id,
                    status=SignalReport.Status.READY,
                    title=proposal.title,
                    summary=proposal.summary,
                    signal_count=0,
                    total_weight=0.0,
                )
                SignalReportArtefact.append_status(
                    team_id=inputs.team_id,
                    report_id=str(report.id),
                    content=SetupProposal(
                        category=proposal.category,  # type: ignore[arg-type]
                        product=CATEGORY_PRODUCTS[proposal.category],
                    ),
                    attribution=attribution,
                    reevaluate_autostart=False,
                )
                SignalReportArtefact.append_status(
                    team_id=inputs.team_id,
                    report_id=str(report.id),
                    content=RepoSelectionResult(
                        repository=inputs.repository,
                        reason="Repository the PostHog setup wizard integrated during onboarding.",
                    ),
                    attribution=attribution,
                    reevaluate_autostart=False,
                )
            report_ids.append(str(report.id))
        return report_ids

    return await database_sync_to_async(_create, thread_sensitive=False)()


@workflow.defn(name="signals-setup-audit")
class SetupAuditWorkflow:
    """Audit a freshly-onboarded team's setup and file proposal reports for the inbox."""

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        # One audit per team, ever: reusing the id makes duplicate starts no-ops, and the
        # proposal-artefact existence check in detect covers reruns after workflow retention.
        return f"signals-setup-audit-{team_id}"

    @workflow.run
    async def run(self, inputs: SetupAuditInputs) -> list[str]:
        with posthoganalytics.new_context(capture_exceptions=False):
            posthoganalytics.tag("team_id", inputs.team_id)
            posthoganalytics.tag("product", "signals")
            return await self._run_impl(inputs)

    async def _run_impl(self, inputs: SetupAuditInputs) -> list[str]:
        detected: DetectedGaps = await workflow.execute_activity(
            detect_setup_gaps_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not detected.gaps:
            return []

        proposals: list[ProposalCopy] = await workflow.execute_activity(
            personalize_proposals_activity,
            PersonalizeInputs(team_id=inputs.team_id, repository=inputs.repository, detected=detected),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if not proposals:
            return []

        return await workflow.execute_activity(
            create_proposal_reports_activity,
            CreateProposalsInputs(team_id=inputs.team_id, repository=inputs.repository, proposals=proposals),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
