from datetime import datetime
from typing import Any

from products.signals.backend.facade import api as signals
from products.today.backend.logic.signal_text import SignalInput


def signal(
    *,
    content: str = "",
    source_product: str = "signals_scout",
    source_type: str = "cross_source_issue",
    source_id: str = "source-1",
    signal_id: str = "signal-1",
    timestamp: str = "2026-10-01T10:00:00+00:00",
    extra: dict[str, Any] | None = None,
) -> SignalInput:
    return SignalInput(
        signal_id=signal_id,
        content=content,
        source_product=source_product,
        source_type=source_type,
        source_id=source_id,
        timestamp=datetime.fromisoformat(timestamp),
        extra=extra or {},
    )


def page_source(
    *,
    summary: str = "",
    solution: str | None = None,
    impact: str | None = None,
    action_prompts: list[str] | None = None,
) -> signals.ReportPageSource:
    return signals.ReportPageSource(
        summary=summary,
        sections=signals.ReportSections(lead="Lead.", impact=impact, solution=solution),
        action_prompts=action_prompts or [],
        repo_slug="example/web",
        signals=[],
    )
