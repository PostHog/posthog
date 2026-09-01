"""Lighthouse audit tool: load one page in a real browser and name what makes it slow.

Field data (`$web_vitals` events) says a route is slow and for how many people. It does not say
which element the browser chose as the LCP, or which of the load phases ran long. The web vitals
scout has had to guess at a candidate by reading the page source, and a guess is what a reader
discounts. Lighthouse answers both questions directly, so a finding can name the element.

An audit drives a real browser at a real page, which is why this is fenced on four sides:
`SIGNALS_LIGHTHOUSE_ALLOWED_HOSTS` (public PostHog pages only), `SIGNALS_LIGHTHOUSE_TEAM_IDS`
(our own project), the internal-only MCP scope on the endpoint, and a per-run cap. The browser
signs in to nothing, so a page behind a login is not merely disallowed — it would report the
login screen's LCP as the page's.

Lab and field measure different things and the scout is told to keep them apart: p75 over real
users decides whether something is a problem, one throttled cold load explains why.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode, urlsplit

from django.conf import settings

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.security.url_validation import is_url_allowed

logger = structlog.get_logger(__name__)

# Lighthouse emulates one device per run and the two disagree, so the caller picks. Desktop is the
# default because it is the profile most of our own traffic arrives on.
FORM_FACTORS = ("desktop", "mobile")
DEFAULT_FORM_FACTOR = "desktop"

# The metrics worth carrying back, mapped to the reader-facing names the scout writes with. The
# full Lighthouse report is a few hundred KB; nearly all of it is detail no finding ever cites.
_METRIC_AUDITS: dict[str, str] = {
    "largest-contentful-paint": "lcp_ms",
    "first-contentful-paint": "fcp_ms",
    "cumulative-layout-shift": "cls",
    "total-blocking-time": "tbt_ms",
    "speed-index": "speed_index_ms",
    "interactive": "tti_ms",
}

# Pass/fail audits that bear on LCP specifically. Lighthouse scores these 0 or 1 with no savings
# estimate, so they never appear among the opportunities below, and they are the checks that most
# often explain a late hero image.
_LCP_CHECK_AUDITS = (
    "prioritize-lcp-image",
    "lcp-lazy-loaded",
    "uses-responsive-images",
    "modern-image-formats",
    "efficient-animated-content",
    "uses-optimized-images",
)

# An opportunity below this is noise next to a multi-second LCP, and listing it invites a finding
# built on a rounding error.
MIN_OPPORTUNITY_SAVINGS_MS = 50
MAX_OPPORTUNITIES = 10

# One audit is a browser load under CPU and network throttling — tens of seconds of a Browserless
# session. A scout corroborating a finding needs one page, or a handful across a route family;
# anything past that is a crawl it should not be running.
MAX_AUDITS_PER_RUN = 5
_RUN_AUDIT_COUNT_KEY = "lighthouse_audit_count"


class LighthouseUnavailableError(RuntimeError):
    """Lighthouse is not provisioned on this deployment, so no audit can run."""


class InvalidLighthouseTargetError(ValueError):
    """The requested URL or the calling team is outside what audits are allowed to reach."""


class LighthouseAuditFailedError(RuntimeError):
    """Browserless or Lighthouse itself could not produce a usable report."""


@frozen
class LcpElement:
    selector: str | None
    snippet: str | None
    node_label: str | None


@frozen
class LcpPhase:
    phase: str
    timing_ms: float | None
    percent: str | None


@frozen
class AuditOpportunity:
    audit_id: str
    title: str
    savings_ms: float | None


@frozen
class LighthouseAudit:
    """One page, one device profile, reduced to what a web vitals finding actually cites."""

    requested_url: str
    final_url: str | None
    form_factor: str
    performance_score: int | None
    metrics: dict[str, float]
    lcp_element: LcpElement | None
    lcp_phases: list[LcpPhase]
    lcp_checks_failed: list[AuditOpportunity]
    opportunities: list[AuditOpportunity]

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "form_factor": self.form_factor,
            "performance_score": self.performance_score,
            "metrics": dict(self.metrics),
            "lcp_element": (
                {
                    "selector": self.lcp_element.selector,
                    "snippet": self.lcp_element.snippet,
                    "node_label": self.lcp_element.node_label,
                }
                if self.lcp_element is not None
                else None
            ),
            "lcp_phases": [
                {"phase": phase.phase, "timing_ms": phase.timing_ms, "percent": phase.percent}
                for phase in self.lcp_phases
            ],
            "lcp_checks_failed": [_opportunity_as_dict(entry) for entry in self.lcp_checks_failed],
            "opportunities": [_opportunity_as_dict(entry) for entry in self.opportunities],
        }


def _opportunity_as_dict(entry: AuditOpportunity) -> dict[str, Any]:
    return {"audit_id": entry.audit_id, "title": entry.title, "savings_ms": entry.savings_ms}


def run_lighthouse_audit(*, team_id: int, url: str, form_factor: str = DEFAULT_FORM_FACTOR) -> LighthouseAudit:
    """Audit one URL and return the reduced report.

    Raises `InvalidLighthouseTargetError` for a target or caller outside the allowlists,
    `LighthouseUnavailableError` when the deployment has no Browserless configured, and
    `LighthouseAuditFailedError` when the run itself fails.
    """
    if form_factor not in FORM_FACTORS:
        raise InvalidLighthouseTargetError(f"form_factor must be one of {', '.join(FORM_FACTORS)}.")
    _assert_team_allowed(team_id)
    target = _assert_url_allowed(url)
    endpoint = _build_performance_url()
    if endpoint is None:
        raise LighthouseUnavailableError("Lighthouse audits are not configured on this deployment.")

    payload = _request_audit(endpoint=endpoint, url=target, form_factor=form_factor)
    report = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(report, dict):
        raise LighthouseAuditFailedError("Lighthouse returned a report in an unrecognized shape.")

    runtime_error = report.get("runtimeError")
    if isinstance(runtime_error, dict) and runtime_error.get("code") not in (None, "NO_ERROR"):
        raise LighthouseAuditFailedError(
            f"Lighthouse could not load the page ({runtime_error.get('code')}): {runtime_error.get('message')}"
        )

    final_url = _final_url(report)
    # A redirect off the allowlist is the login-wall case: the audit ran, but not on the page that
    # was asked for, and its numbers describe wherever it landed. Fail rather than hand the scout a
    # measurement of the sign-in screen under the requested URL's name.
    if final_url is not None and not _host_allowed(final_url):
        raise InvalidLighthouseTargetError(
            f"{target} redirected to {final_url}, which is outside the allowed hosts — "
            "the audit would describe that page instead. Pages behind a login cannot be audited."
        )

    return _reduce_report(report, requested_url=target, final_url=final_url, form_factor=form_factor)


def audits_remaining_for_run(run_metadata: dict[str, Any] | None) -> int:
    """How many audits this run may still spend, read off its own metadata counter."""
    spent = (run_metadata or {}).get(_RUN_AUDIT_COUNT_KEY) or 0
    return max(0, MAX_AUDITS_PER_RUN - int(spent))


def _assert_team_allowed(team_id: int) -> None:
    allowed = settings.SIGNALS_LIGHTHOUSE_TEAM_IDS
    if team_id not in allowed:
        raise InvalidLighthouseTargetError("Lighthouse audits are not enabled for this project.")


def _assert_url_allowed(url: str) -> str:
    target = (url or "").strip()
    if not target:
        raise InvalidLighthouseTargetError("A url is required.")
    parsed = urlsplit(target)
    if parsed.scheme != "https":
        raise InvalidLighthouseTargetError("Only https urls can be audited.")
    if not _host_allowed(target):
        allowed = ", ".join(sorted(settings.SIGNALS_LIGHTHOUSE_ALLOWED_HOSTS)) or "(none configured)"
        raise InvalidLighthouseTargetError(
            f"{parsed.hostname or target} is not an auditable host. Allowed hosts: {allowed}. "
            "Pages behind a login are excluded — an audit signs in to nothing, so it would "
            "measure the login screen."
        )
    ok, reason = is_url_allowed(target)
    if not ok:
        raise InvalidLighthouseTargetError(f"That url cannot be fetched: {reason}")
    return target


def _host_allowed(url: str) -> bool:
    hostname = urlsplit(url).hostname
    if not hostname:
        return False
    return hostname.lower() in settings.SIGNALS_LIGHTHOUSE_ALLOWED_HOSTS


def _build_performance_url() -> str | None:
    # Read settings at call time (not import) so `override_settings` works in tests. Strip an
    # inline comment a bash-sourced .env may have left in the value, as the heatmap path does.
    base_url = (settings.LIGHTHOUSE_BROWSERLESS_URL or "").split("#", 1)[0].strip()
    parsed = urlsplit(base_url) if base_url else None
    host = parsed.hostname if parsed else None
    if not parsed or not host:
        return None
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    scheme = "http" if parsed.scheme in ("http", "ws") else "https"
    params = {
        "token": settings.LIGHTHOUSE_BROWSERLESS_TOKEN,
        "timeout": str(settings.LIGHTHOUSE_BROWSERLESS_TIMEOUT_MS),
    }
    return f"{scheme}://{netloc}/performance?{urlencode(params)}"


def _request_audit(*, endpoint: str, url: str, form_factor: str) -> dict[str, Any]:
    body = {
        "url": url,
        "config": {
            "extends": "lighthouse:default",
            "settings": {
                "onlyCategories": ["performance"],
                "formFactor": form_factor,
                "screenEmulation": _screen_emulation(form_factor),
            },
        },
    }
    timeout = (
        settings.LIGHTHOUSE_BROWSERLESS_CONNECT_TIMEOUT_MS / 1000,
        settings.LIGHTHOUSE_BROWSERLESS_TIMEOUT_MS / 1000 + 30,
    )
    started = time.monotonic()
    try:
        response = requests.post(endpoint, json=body, timeout=timeout)
    except Exception as e:
        logger.warning("signals.lighthouse.request_failed", form_factor=form_factor, error=str(e))
        raise LighthouseAuditFailedError(f"The audit request failed: {_redact(str(e))}") from None

    elapsed_ms = round((time.monotonic() - started) * 1000)
    if response.status_code != 200:
        logger.warning(
            "signals.lighthouse.request_rejected",
            form_factor=form_factor,
            status=response.status_code,
            latency_ms=elapsed_ms,
        )
        raise LighthouseAuditFailedError(f"The audit failed ({response.status_code}): {_redact(response.text[:500])}")
    try:
        payload = response.json()
    except ValueError:
        raise LighthouseAuditFailedError("The audit returned a body that is not JSON.") from None
    if not isinstance(payload, dict):
        raise LighthouseAuditFailedError("The audit returned a body that is not a Lighthouse report.")
    logger.info("signals.lighthouse.audited", form_factor=form_factor, latency_ms=elapsed_ms)
    return payload


def _screen_emulation(form_factor: str) -> dict[str, Any]:
    if form_factor == "mobile":
        return {"mobile": True, "width": 412, "height": 823, "deviceScaleFactor": 1.75, "disabled": False}
    return {"mobile": False, "width": 1350, "height": 940, "deviceScaleFactor": 1, "disabled": False}


def _redact(text: str) -> str:
    # The endpoint carries the Browserless token in its query string, and both the exception text
    # and the error body can quote the url back.
    token = settings.LIGHTHOUSE_BROWSERLESS_TOKEN
    return text.replace(token, "[redacted]") if token else text


def _final_url(report: dict[str, Any]) -> str | None:
    # Lighthouse renamed this field; read whichever the running version emits.
    for key in ("finalDisplayedUrl", "finalUrl", "mainDocumentUrl"):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _reduce_report(
    report: dict[str, Any], *, requested_url: str, final_url: str | None, form_factor: str
) -> LighthouseAudit:
    raw_audits = report.get("audits")
    audits: dict[str, Any] = raw_audits if isinstance(raw_audits, dict) else {}
    return LighthouseAudit(
        requested_url=requested_url,
        final_url=final_url,
        form_factor=form_factor,
        performance_score=_performance_score(report),
        metrics=_metrics(audits),
        lcp_element=_lcp_element(audits),
        lcp_phases=_lcp_phases(audits),
        lcp_checks_failed=_failed_lcp_checks(audits),
        opportunities=_opportunities(audits),
    )


def _performance_score(report: dict[str, Any]) -> int | None:
    categories = report.get("categories")
    if not isinstance(categories, dict):
        return None
    performance = categories.get("performance")
    if not isinstance(performance, dict):
        return None
    score = performance.get("score")
    return round(score * 100) if isinstance(score, int | float) else None


def _metrics(audits: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for audit_id, name in _METRIC_AUDITS.items():
        audit = audits.get(audit_id)
        if not isinstance(audit, dict):
            continue
        value = audit.get("numericValue")
        if isinstance(value, int | float):
            metrics[name] = round(float(value), 3)
    return metrics


def _lcp_element(audits: dict[str, Any]) -> LcpElement | None:
    node = _first_node(audits.get("largest-contentful-paint-element"))
    if node is None:
        return None
    return LcpElement(
        selector=_as_text(node.get("selector")),
        snippet=_as_text(node.get("snippet")),
        node_label=_as_text(node.get("nodeLabel")),
    )


def _first_node(audit: Any) -> dict[str, Any] | None:
    # The element sits at `details.items[].items[].node` on current Lighthouse and directly at
    # `details.items[].node` on older ones, so walk both levels rather than pinning a shape.
    if not isinstance(audit, dict):
        return None
    details = audit.get("details")
    if not isinstance(details, dict):
        return None
    for item in details.get("items") or []:
        if not isinstance(item, dict):
            continue
        node = item.get("node")
        if isinstance(node, dict):
            return node
        for nested in item.get("items") or []:
            if isinstance(nested, dict) and isinstance(nested.get("node"), dict):
                return nested["node"]
    return None


def _lcp_phases(audits: dict[str, Any]) -> list[LcpPhase]:
    audit = audits.get("largest-contentful-paint-element")
    if not isinstance(audit, dict):
        return []
    details = audit.get("details")
    if not isinstance(details, dict):
        return []
    phases: list[LcpPhase] = []
    for item in details.get("items") or []:
        if not isinstance(item, dict):
            continue
        for row in item.get("items") or []:
            if not isinstance(row, dict) or "phase" not in row:
                continue
            timing = row.get("timing")
            phases.append(
                LcpPhase(
                    phase=str(row["phase"]),
                    timing_ms=round(float(timing), 3) if isinstance(timing, int | float) else None,
                    percent=_as_text(row.get("percent")),
                )
            )
    return phases


def _failed_lcp_checks(audits: dict[str, Any]) -> list[AuditOpportunity]:
    failed: list[AuditOpportunity] = []
    for audit_id in _LCP_CHECK_AUDITS:
        audit = audits.get(audit_id)
        if not isinstance(audit, dict):
            continue
        score = audit.get("score")
        if not isinstance(score, int | float) or score >= 1:
            continue
        failed.append(
            AuditOpportunity(
                audit_id=audit_id,
                title=_as_text(audit.get("title")) or audit_id,
                savings_ms=_savings_ms(audit),
            )
        )
    return failed


def _opportunities(audits: dict[str, Any]) -> list[AuditOpportunity]:
    found: list[AuditOpportunity] = []
    for audit_id, audit in audits.items():
        if not isinstance(audit, dict):
            continue
        details = audit.get("details")
        if not isinstance(details, dict) or details.get("type") != "opportunity":
            continue
        savings = _savings_ms(audit)
        if savings is None or savings < MIN_OPPORTUNITY_SAVINGS_MS:
            continue
        found.append(
            AuditOpportunity(
                audit_id=audit_id,
                title=_as_text(audit.get("title")) or audit_id,
                savings_ms=savings,
            )
        )
    found.sort(key=lambda entry: entry.savings_ms or 0, reverse=True)
    return found[:MAX_OPPORTUNITIES]


def _savings_ms(audit: dict[str, Any]) -> float | None:
    details = audit.get("details")
    if isinstance(details, dict):
        savings = details.get("overallSavingsMs")
        if isinstance(savings, int | float):
            return round(float(savings), 1)
    numeric = audit.get("numericValue")
    return round(float(numeric), 1) if isinstance(numeric, int | float) else None


def _as_text(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None
