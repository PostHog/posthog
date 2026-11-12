"""Shared parts of the GitHub security alert emitters (Dependabot, code scanning, secret scanning).

Alerts are numbered within a repository, and a multi-repository connection syncs one table per
repository, so `number` can repeat across a team's tables. The alert's `html_url` names the
repository and the number, so it is the signal source id.
"""

import re
from collections.abc import Iterable
from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission.registry import SignalEmitterOutput

logger = get_logger(__name__)

_REPOSITORY_RE = re.compile(r"^https?://[^/]+/(?P<repository>[^/]+/[^/]+)/security/")


def alert_text(value: Any, limit: int | None = None) -> str | None:
    """A stripped string, or None for empty values and the JSON `null` that JSONExtractRaw returns."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "null":
        return None
    return text[:limit] if limit else text


def repository_from_html_url(html_url: Any) -> str | None:
    """`owner/repo` from an alert URL such as `https://github.com/owner/repo/security/dependabot/3`."""
    if not isinstance(html_url, str):
        return None
    match = _REPOSITORY_RE.match(html_url.strip())
    return match.group("repository") if match else None


def build_github_alert_output(
    *,
    team_id: int,
    record: dict[str, Any],
    source_product: str,
    title: str | None,
    details: Iterable[str | None],
    extra_fields: tuple[str, ...],
) -> SignalEmitterOutput | None:
    try:
        html_url = record["html_url"]
    except KeyError as e:
        msg = f"{source_product} record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    source_id = alert_text(html_url)
    if not source_id or not title:
        logger.info(
            f"Ignoring {source_product} record with empty html_url or title",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    repository = repository_from_html_url(source_id)
    lines = [title]
    if repository:
        lines.append(f"Repository: {repository}")
    lines.extend(detail for detail in details if detail)
    extra = build_extra(record, extra_fields, ())
    extra["repository"] = repository
    return SignalEmitterOutput(
        source_product=source_product,
        source_type="scanner_finding",
        source_id=source_id,
        description="\n".join(lines),
        weight=1.0,
        extra=extra,
    )
