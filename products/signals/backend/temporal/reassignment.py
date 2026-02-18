import json
import asyncio
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

import structlog
import temporalio
from pydantic import BaseModel, Field

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.coherence_judge import NewReportInfo, ReportDescription
from products.signals.backend.temporal.llm import call_llm
from products.signals.backend.temporal.types import SignalData, render_signals_to_text

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


ASSIGN_SIGNAL_SYSTEM_PROMPT = """You are a signal classification assistant. You are given a single signal and a list of candidate reports.
Your job is to decide which report the signal belongs to.

Each report has a title and description. Pick the one report that best matches the signal's content, source, and context.

Respond with a JSON object containing the index (0-based) of the chosen report:
{"report_index": <integer>}

Return ONLY valid JSON, no other text. The first token of output must be {"""


def _build_assign_signal_prompt(
    signal: SignalData,
    report_options: list[ReportDescription],
) -> str:
    lines = [f"SIGNAL TO CLASSIFY:\n\n{render_signals_to_text([signal])}\n\nCANDIDATE REPORTS:\n"]
    for i, report in enumerate(report_options):
        lines.append(f"Report {i}: {report.title}")
        lines.append(f"  Summary: {report.summary}\n")
    return "\n".join(lines)


class AssignSignalToReportResponse(BaseModel):
    report_index: int = Field(description="0-based index of the chosen report")


async def assign_signal_to_report_by_llm(
    signal: SignalData,
    report_options: list[ReportDescription],
) -> int:
    user_prompt = _build_assign_signal_prompt(signal, report_options)

    def validate(text: str) -> int:
        data = json.loads(text)
        result = AssignSignalToReportResponse.model_validate(data)

        if result.report_index < 0 or result.report_index >= len(report_options):
            raise ValueError(f"report_index {result.report_index} out of range [0, {len(report_options) - 1}]")

        return result.report_index

    return await call_llm(
        system_prompt=ASSIGN_SIGNAL_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        temperature=0.2,
    )


@dataclass
class ClassifySignalsInput:
    team_id: int
    signals: list[SignalData]
    new_reports: list[NewReportInfo]


@dataclass
class ClassifySignalsOutput:
    assignments: list[int]  # assignments[signal_idx] = report_idx


@temporalio.activity.defn
async def classify_signals_activity(input: ClassifySignalsInput) -> ClassifySignalsOutput:
    try:
        report_options = [ReportDescription(title=r.title, summary=r.summary) for r in input.new_reports]

        assignments = await asyncio.gather(
            *(assign_signal_to_report_by_llm(signal, report_options) for signal in input.signals)
        )

        logger.debug(
            f"Classified {len(input.signals)} signals into {len(input.new_reports)} buckets",
            team_id=input.team_id,
        )
        return ClassifySignalsOutput(assignments=list(assignments))

    except Exception as e:
        logger.exception(
            f"Failed to classify signals: {e}",
            team_id=input.team_id,
        )
        raise


@dataclass
class SaveReassignmentInput:
    team_id: int
    original_report_id: str
    signals: list[SignalData]
    new_reports: list[NewReportInfo]
    assignments: list[int]  # assignments[signal_idx] = report_idx


@dataclass
class CreatedReport:
    report_id: str
    title: str
    summary: str
    signal_count: int
    total_weight: float


@dataclass
class SaveReassignmentOutput:
    created_reports: list[CreatedReport]


@temporalio.activity.defn
async def save_reassignment_activity(input: SaveReassignmentInput) -> SaveReassignmentOutput:
    try:
        # Group signals by their assigned report index
        buckets: dict[int, list[SignalData]] = {}
        for signal_idx, report_idx in enumerate(input.assignments):
            buckets.setdefault(report_idx, []).append(input.signals[signal_idx])

        # Only create reports for non-empty buckets
        non_empty_reports = [(idx, info) for idx, info in enumerate(input.new_reports) if idx in buckets]

        def create_reports_emit_signals_and_mark_original() -> list[tuple[SignalReport, int]]:
            with transaction.atomic():
                created = []
                for report_idx, info in non_empty_reports:
                    signals_in_bucket = buckets[report_idx]
                    report = SignalReport.objects.create(
                        team_id=input.team_id,
                        status=SignalReport.Status.POTENTIAL,
                        total_weight=sum(s.weight for s in signals_in_bucket),
                        signal_count=len(signals_in_bucket),
                        title=info.title,
                        summary=info.summary,
                    )
                    created.append((report, report_idx))

                # Re-emit each signal to ClickHouse with its new report_id.
                # Inside the atomic block so that if any emit fails, the whole
                # transaction (report creation + original mark-as-failed) rolls back.
                for report, report_idx in created:
                    for signal in buckets[report_idx]:
                        metadata = {
                            "source_product": signal.source_product,
                            "source_type": signal.source_type,
                            "source_id": signal.source_id,
                            "weight": signal.weight,
                            "report_id": str(report.id),
                            "extra": signal.extra,
                        }

                        emit_embedding_request(
                            content=signal.content,
                            team_id=input.team_id,
                            product="signals",
                            document_type="signal",
                            rendering="plain",
                            document_id=signal.signal_id,
                            models=[EMBEDDING_MODEL.value],
                            timestamp=timezone.now(),
                            metadata=metadata,
                        )

                SignalReport.objects.filter(id=input.original_report_id).update(
                    status=SignalReport.Status.FAILED,
                    error=f"Split into {len(created)} reports by coherence judge",
                    updated_at=timezone.now(),
                )

                return created

        created_reports = await database_sync_to_async(
            create_reports_emit_signals_and_mark_original, thread_sensitive=False
        )()

        result = [
            CreatedReport(
                report_id=str(report.id),
                title=report.title or "",
                summary=input.new_reports[report_idx].summary,
                signal_count=len(buckets[report_idx]),
                total_weight=sum(s.weight for s in buckets[report_idx]),
            )
            for report, report_idx in created_reports
        ]

        logger.info(
            f"Reassigned {len(input.signals)} signals from report {input.original_report_id} "
            f"into {len(result)} new reports (skipped {len(input.new_reports) - len(result)} empty buckets)",
            original_report_id=input.original_report_id,
            new_report_ids=[c.report_id for c in result],
        )

        return SaveReassignmentOutput(created_reports=result)

    except Exception as e:
        logger.exception(
            f"Failed to save reassignment for report {input.original_report_id}: {e}",
            original_report_id=input.original_report_id,
        )
        raise
