from __future__ import annotations

import uuid
import logging

from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    PriorityAssessment,
    ReportPresentationOutput,
    ReportResearchOutput,
    SignalFinding,
)
from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession
from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, OutputFn
from products.tasks.backend.services.mts_example.prompts import (
    build_actionability_prompt,
    build_discovery_prompt,
    build_presentation_prompt,
    build_priority_prompt,
    build_research_prompt,
)
from products.tasks.backend.services.mts_example.schemas import CursedItemCandidates

logger = logging.getLogger(__name__)

MAX_CURSED_ITEMS = 10


async def run_cursed_identifier_research(
    context: CustomPromptSandboxContext,
    *,
    branch: str = "master",
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> ReportResearchOutput:
    """Demo multi-turn session whose output shape matches the Signals pipeline.

    Turn flow: discovery → N research (one per discovered item) → actionability
    → priority (skipped when not actionable) → presentation.
    """
    if output_fn:
        output_fn(f"Discovery: asking agent for up to {MAX_CURSED_ITEMS} cursed items...")

    session, candidates = await MultiTurnSession.start(
        prompt=build_discovery_prompt(MAX_CURSED_ITEMS),
        context=context,
        model=CursedItemCandidates,
        branch=branch,
        step_name="mts_example_discovery",
        verbose=verbose,
        output_fn=output_fn,
    )

    total = len(candidates.items)
    if total == 0:
        await session.end()
        raise RuntimeError("Discovery turn returned zero cursed items — nothing to research.")

    if output_fn:
        output_fn(f"Discovery done: {total} cursed item(s). Researching each individually...")

    findings: list[SignalFinding] = []
    for index, item in enumerate(candidates.items, start=1):
        synthetic_signal_id = str(uuid.uuid4())
        if output_fn:
            output_fn(f"Research {index}/{total}: {item.kind} {item.content!r} @ {item.file_path}:{item.line_number}")
        finding = await session.send_followup(
            build_research_prompt(
                item_content=item.content,
                item_kind=item.kind,
                file_path=item.file_path,
                line_number=item.line_number,
                cursedness_reason=item.cursedness_reason,
                index=index,
                total=total,
                synthetic_signal_id=synthetic_signal_id,
            ),
            SignalFinding,
            label=f"research_item_{index}_of_{total}",
        )
        # Pin the synthetic signal_id if the model drifted
        if finding.signal_id != synthetic_signal_id:
            finding = finding.model_copy(update={"signal_id": synthetic_signal_id})
        findings.append(finding)

    if output_fn:
        output_fn("Assessing actionability...")
    actionability = await session.send_followup(
        build_actionability_prompt(total),
        ActionabilityAssessment,
        label="actionability",
    )

    priority: PriorityAssessment | None = None
    if actionability.actionability != ActionabilityChoice.NOT_ACTIONABLE:
        if output_fn:
            output_fn("Assessing priority...")
        priority = await session.send_followup(
            build_priority_prompt(total),
            PriorityAssessment,
            label="priority",
        )

    if output_fn:
        output_fn("Writing title and summary...")
    presentation = await session.send_followup(
        build_presentation_prompt(total),
        ReportPresentationOutput,
        label="presentation",
    )

    await session.end()
    logger.info("mts_example: completed with %d finding(s)", len(findings))
    return ReportResearchOutput(
        title=presentation.title,
        summary=presentation.summary,
        findings=findings,
        actionability=actionability,
        priority=priority,
    )
