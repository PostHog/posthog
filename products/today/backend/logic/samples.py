import json
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from posthog.dataclasses import frozen

from products.signals.backend.facade import api as signals

SAMPLE_ID_PREFIX = "sample-"
_SAMPLES_PATH = Path(__file__).with_name("sample_reports.json")


@frozen
class SampleSignal:
    source_product: str
    source_type: str
    content: str
    hours_ago: float


@frozen
class SampleReport:
    id: str
    title: str
    summary: str
    hours_ago: float
    priority: str | None
    actionability: str | None
    status: str
    source_products: list[str]
    pull_request_url: str | None
    metrics: list[dict[str, Any]]
    signals: list[SampleSignal]


@cache
def _samples() -> dict[str, SampleReport]:
    rows = json.loads(_SAMPLES_PATH.read_text())
    return {
        row["id"]: SampleReport(**{**row, "signals": [SampleSignal(**signal) for signal in row["signals"]]})
        for row in rows
    }


def is_sample_id(report_id: str) -> bool:
    return report_id.startswith(SAMPLE_ID_PREFIX)


def sample_report(report_id: str) -> SampleReport | None:
    return _samples().get(report_id)


def _sample_signals(sample: SampleReport, now: datetime) -> list[signals.ReportSignal]:
    return [
        signals.ReportSignal(
            signal_id=f"{sample.id}-signal-{index}",
            content=signal.content,
            source_product=signal.source_product,
            source_type=signal.source_type,
            source_id=f"{sample.id}-source-{index}",
            timestamp=now - timedelta(hours=signal.hours_ago),
            extra={},
        )
        for index, signal in enumerate(sample.signals)
    ]


def sample_page_source(sample: SampleReport) -> signals.ReportPageSource:
    return signals.ReportPageSource(
        summary=sample.summary,
        sections=signals.report_sections(sample.summary),
        status=sample.status,
        actionability=sample.actionability,
        already_addressed=False,
        has_pull_requests=sample.pull_request_url is not None,
        suggested_prompts=[],
        repo_slug=None,
        signals=_sample_signals(sample, datetime.now(UTC)),
    )
