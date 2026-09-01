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

import re
import json
import time
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from django.conf import settings

import requests
import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.security.url_validation import is_url_allowed

logger = structlog.get_logger(__name__)

# Audits share the heatmap Browserless fleet but hold a session an order of magnitude longer, so
# their spend and failure rate have to be separable from the screenshot traffic next to them.
LIGHTHOUSE_REQUESTS = Counter(
    "signals_lighthouse_requests",
    "Lighthouse audit requests to Browserless by outcome",
    labelnames=["form_factor", "outcome"],
)
LIGHTHOUSE_REQUEST_SECONDS = Histogram(
    "signals_lighthouse_request_duration_seconds",
    "Latency of a single Browserless /performance call",
    labelnames=["form_factor"],
    buckets=(1, 5, 10, 20, 30, 45, 60, 90, 120, float("inf")),
)

# Matches the heatmap path's `token=` scrubber. `urlencode` percent-encodes a token containing
# `/`, `+`, or `=`, so a literal replace alone misses the spelling that actually lands in an
# echoed url.
_TOKEN_QS_RE = re.compile(r"(token=)[^&\s\"']+")

# Runtime gate on which teams may spend an audit, so the capability can be switched on for a
# team — or off fleet-wide — without an infra deploy. Payload shape:
#
#     {"enabled": true, "team_ids": [2]}
#
# `enabled: false` is the kill switch. `team_ids` replaces the settings default when present;
# absent, the deploy-time `SIGNALS_LIGHTHOUSE_TEAM_IDS` still applies, so an unset flag leaves
# the internal-project-only posture untouched.
#
# The flag deliberately cannot widen `SIGNALS_LIGHTHOUSE_ALLOWED_HOSTS`. Which pages a browser
# may be pointed at is the security fence and stays deploy-gated; this only picks who may spend
# a Browserless session on the pages that fence already allows.
SIGNALS_LIGHTHOUSE_FLAG = "signals-lighthouse-audit"

# Enablement is team-list-in-payload rather than per-user, so the read uses a fixed distinct_id.
LIGHTHOUSE_DISCOVERY_DISTINCT_ID = "internal_signals_lighthouse_discovery"

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

# Lighthouse 12 introduced "insight" audits (carried over from DevTools) and Lighthouse 13
# dropped the legacy per-check audits entirely — `largest-contentful-paint-element`,
# `prioritize-lcp-image`, and `lcp-lazy-loaded` are simply absent from a v13 report. Both
# spellings are read so an audit keeps naming the element whichever version the fleet ships,
# and so a Browserless upgrade can't quietly turn every finding back into a guess.
# Insight audits carry the LCP element as a `type: node` entry and the phase table alongside it.
_LCP_INSIGHT_AUDITS = ("lcp-breakdown-insight", "lcp-discovery-insight")
_LEGACY_LCP_ELEMENT_AUDIT = "largest-contentful-paint-element"

# `lcp-discovery-insight` carries its pass/fail checks as a checklist keyed by check name —
# `priorityHinted` false is the modern spelling of "this hero image needs fetchpriority=high".
_LCP_CHECKLIST_AUDIT = "lcp-discovery-insight"

# Legacy pass/fail audits that bear on LCP. Absent on Lighthouse 13; kept for older fleets. Several
# also carry a savings estimate, so one can appear both here and under `opportunities` — that is
# deliberate: this list answers "what is wrong with the LCP", the other "what is worth the most".
_LCP_CHECK_AUDITS = (
    "prioritize-lcp-image",
    "lcp-lazy-loaded",
    "uses-responsive-images",
    "modern-image-formats",
    "efficient-animated-content",
    "uses-optimized-images",
)

# `metricSavings` keys whose value is milliseconds. CLS is excluded because its saving is a
# unitless layout-shift score, and reporting 0.101 alongside "ms" would be a wrong number rather
# than a missing one.
_TIME_METRIC_SAVINGS_KEYS = ("LCP", "FCP", "TBT", "INP")

# An opportunity below this is noise next to a multi-second LCP, and listing it invites a finding
# built on a rounding error.
MIN_OPPORTUNITY_SAVINGS_MS = 50
MAX_OPPORTUNITIES = 10

# Cap on a single page-derived string (selector, snippet, alt text) returned to a scout.
MAX_PAGE_TEXT_LENGTH = 600

# One audit is a browser load under CPU and network throttling — tens of seconds of a Browserless
# session. A scout corroborating a finding needs one page, or a handful across a route family;
# anything past that is a crawl it should not be running.
MAX_AUDITS_PER_RUN = 5
# Public because the view reserves against it: a private constant on one side and a string
# literal on the other agree only by coincidence, and a rename would silently uncap the budget.
RUN_AUDIT_COUNT_KEY = "lighthouse_audit_count"


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
    lighthouse_version: str | None
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
            "lighthouse_version": self.lighthouse_version,
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


@frozen
class PreparedAudit:
    """A validated, ready-to-send audit. Holding this means every cheap fence has passed and the
    next step is a real browser load."""

    target: str
    endpoint: str
    form_factor: str


def prepare_lighthouse_audit(*, team_id: int, url: str, form_factor: str = DEFAULT_FORM_FACTOR) -> PreparedAudit:
    """Run every check that costs nothing, so a caller can reject before spending anything.

    Split from the audit itself because the per-run budget is reserved between the two: a bad
    host, an http url, a team without the capability, or a deployment with no Browserless should
    not cost a slot, since none of them start a browser.

    Raises `InvalidLighthouseTargetError` for a target or caller outside the allowlists, and
    `LighthouseUnavailableError` when the deployment has no Browserless configured.
    """
    if form_factor not in FORM_FACTORS:
        raise InvalidLighthouseTargetError(f"form_factor must be one of {', '.join(FORM_FACTORS)}.")
    _assert_team_allowed(team_id)
    target = _assert_url_allowed(url)
    endpoint = _build_performance_url()
    if endpoint is None:
        raise LighthouseUnavailableError("Lighthouse audits are not configured on this deployment.")
    return PreparedAudit(target=target, endpoint=endpoint, form_factor=form_factor)


def run_lighthouse_audit(*, team_id: int, url: str, form_factor: str = DEFAULT_FORM_FACTOR) -> LighthouseAudit:
    """Validate and audit one URL in one call. Callers that meter the audit prepare first."""
    return execute_lighthouse_audit(prepare_lighthouse_audit(team_id=team_id, url=url, form_factor=form_factor))


def execute_lighthouse_audit(prepared: PreparedAudit) -> LighthouseAudit:
    """Spend the browser load for an already-validated audit and return the reduced report.

    Raises `LighthouseAuditFailedError` when the run itself fails, and
    `InvalidLighthouseTargetError` when the page turns out to have left the allowed hosts.
    """
    target, endpoint, form_factor = prepared.target, prepared.endpoint, prepared.form_factor
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
    #
    # Fails CLOSED on an unknown final url. This is the only control on where the browser actually
    # ended up — the SSRF checks upstream only ever saw the requested url, and Browserless resolves
    # DNS and follows redirects itself. A report that cannot be attributed to a host is not a report
    # worth returning, so an absent field is treated as a failure rather than a pass.
    if final_url is None:
        raise LighthouseAuditFailedError(
            "The report does not say which page it ended on, so it cannot be attributed to the "
            "requested url. Nothing was returned."
        )
    if not _host_allowed(final_url):
        raise InvalidLighthouseTargetError(
            f"{target} redirected to {final_url}, which is outside the allowed hosts — "
            "the audit would describe that page instead. Pages behind a login cannot be audited."
        )

    audit = _reduce_report(report, requested_url=target, final_url=final_url, form_factor=form_factor)
    if not audit.metrics:
        # No metric audit parsed at all means the shape changed or the run produced nothing usable.
        # Returning a 200 full of nulls would read as "this page has no problems".
        raise LighthouseAuditFailedError(
            f"The report carried no usable metrics (Lighthouse {audit.lighthouse_version or 'unknown'})."
        )
    return audit


def audits_remaining_for_run(run_metadata: dict[str, Any] | None) -> int:
    """How many audits this run may still spend, read off its own metadata counter.

    `metadata` is a shared JSON column, so a non-integer value is treated as zero spent rather
    than raising — the same guard the structured-output counter uses.
    """
    spent = (run_metadata or {}).get(RUN_AUDIT_COUNT_KEY)
    return max(0, MAX_AUDITS_PER_RUN - (spent if isinstance(spent, int) else 0))


def _assert_team_allowed(team_id: int) -> None:
    if team_id not in enabled_team_ids():
        raise InvalidLighthouseTargetError("Lighthouse audits are not enabled for this project.")


def enabled_team_ids() -> set[int]:
    """Teams whose scouts may spend an audit: the flag payload when it says, else settings.

    An unreadable or malformed payload falls back to the settings allowlist rather than opening
    up or shutting down — a flag read must not be able to hand the capability to a team the
    deploy never granted it to, nor take it away from the internal project by going down.
    """
    payload = _read_flag_payload()
    if payload is None:
        return settings.SIGNALS_LIGHTHOUSE_TEAM_IDS
    if payload.get("enabled") is False:
        return set()
    raw_team_ids = payload.get("team_ids")
    if not isinstance(raw_team_ids, list):
        return settings.SIGNALS_LIGHTHOUSE_TEAM_IDS
    from_flag = {int(team_id) for team_id in raw_team_ids if isinstance(team_id, int)}
    # A present-but-empty list is a deliberate "nobody", not a parse failure.
    return from_flag


def _read_flag_payload() -> dict | None:
    """Read + parse the `signals-lighthouse-audit` payload once. `None` on absent/malformed/error.

    The flag must stay 100%-on for the payload to be served to the synthetic discovery
    distinct_id; `match_value=True` forces the true-variant payload under local evaluation.
    Mirrors `scout_harness/team_limits._read_flag_payload`.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            SIGNALS_LIGHTHOUSE_FLAG, LIGHTHOUSE_DISCOVERY_DISTINCT_ID, match_value=True
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None


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
                "throttling": _throttling(form_factor),
                # `lighthouse:default` emulates a mobile UA. Left on for a desktop run, the page
                # can serve mobile assets, so the "desktop" report would describe neither profile.
                # False keeps the real desktop Chrome UA rather than pinning a version string here.
                "emulatedUserAgent": form_factor != "desktop",
            },
        },
    }
    timeout = (
        settings.LIGHTHOUSE_BROWSERLESS_CONNECT_TIMEOUT_MS / 1000,
        settings.LIGHTHOUSE_BROWSERLESS_TIMEOUT_MS / 1000 + 15,
    )
    started = time.monotonic()
    try:
        response = requests.post(endpoint, json=body, timeout=timeout)
    except Exception as e:
        # `str(e)` on a requests error quotes the full url, token query string included, so it is
        # scrubbed for the log line exactly as it is for the raised message.
        logger.warning("signals.lighthouse.request_failed", form_factor=form_factor, error=_redact(str(e)))
        LIGHTHOUSE_REQUESTS.labels(form_factor=form_factor, outcome="error").inc()
        raise LighthouseAuditFailedError(f"The audit request failed: {_redact(str(e))}") from None

    elapsed_ms = round((time.monotonic() - started) * 1000)
    LIGHTHOUSE_REQUEST_SECONDS.labels(form_factor=form_factor).observe(elapsed_ms / 1000)
    if response.status_code != 200:
        logger.warning(
            "signals.lighthouse.request_rejected",
            form_factor=form_factor,
            status=response.status_code,
            latency_ms=elapsed_ms,
        )
        LIGHTHOUSE_REQUESTS.labels(form_factor=form_factor, outcome="rejected").inc()
        raise LighthouseAuditFailedError(f"The audit failed ({response.status_code}): {_redact(response.text[:500])}")

    # A report carries base64 screenshot blobs, so it is megabytes even when healthy. Check the
    # length before `.json()` parses it into worker memory.
    body_bytes = len(response.content or b"")
    if body_bytes > settings.LIGHTHOUSE_REPORT_MAX_BYTES:
        LIGHTHOUSE_REQUESTS.labels(form_factor=form_factor, outcome="oversized").inc()
        raise LighthouseAuditFailedError(f"The audit returned an implausibly large report ({body_bytes} bytes).")
    try:
        payload = response.json()
    except ValueError:
        LIGHTHOUSE_REQUESTS.labels(form_factor=form_factor, outcome="unparseable").inc()
        raise LighthouseAuditFailedError("The audit returned a body that is not JSON.") from None
    if not isinstance(payload, dict):
        LIGHTHOUSE_REQUESTS.labels(form_factor=form_factor, outcome="unparseable").inc()
        raise LighthouseAuditFailedError("The audit returned a body that is not a Lighthouse report.")
    logger.info("signals.lighthouse.audited", form_factor=form_factor, latency_ms=elapsed_ms, bytes=body_bytes)
    LIGHTHOUSE_REQUESTS.labels(form_factor=form_factor, outcome="ok").inc()
    return payload


def _screen_emulation(form_factor: str) -> dict[str, Any]:
    if form_factor == "mobile":
        return {"mobile": True, "width": 412, "height": 823, "deviceScaleFactor": 1.75, "disabled": False}
    return {"mobile": False, "width": 1350, "height": 940, "deviceScaleFactor": 1, "disabled": False}


def _throttling(form_factor: str) -> dict[str, Any]:
    """Lighthouse's own presets, sent explicitly per form factor.

    `lighthouse:default` throttles like a slow 4G phone with a 4x CPU slowdown. Setting only
    `formFactor` and `screenEmulation` leaves that in place, so a "desktop" run reports a desktop
    viewport measured over a mobile connection — numbers that cannot be compared against the
    desktop field p75 the audit exists to explain. These mirror `desktopDense4G` and `mobileSlow4G`.
    """
    if form_factor == "desktop":
        return {
            "rttMs": 40,
            "throughputKbps": 10 * 1024,
            "cpuSlowdownMultiplier": 1,
            "requestLatencyMs": 0,
            "downloadThroughputKbps": 0,
            "uploadThroughputKbps": 0,
        }
    return {
        "rttMs": 150,
        "throughputKbps": 1.6 * 1024,
        "cpuSlowdownMultiplier": 4,
        "requestLatencyMs": 150 * 3.75,
        "downloadThroughputKbps": 1.6 * 1024 * 0.9,
        "uploadThroughputKbps": 750 * 0.9,
    }


def _redact(text: str) -> str:
    """Scrub the Browserless token from anything that reaches an error message or a log.

    The endpoint carries the token in its query string, and both the exception text and the
    error body can quote the url back. A literal replace alone is not enough: `urlencode`
    percent-encodes a token containing `/`, `+`, or `=` (ordinary in base64-ish secrets), so the
    echoed url holds a spelling the raw value never matches. The `token=` pattern catches those,
    matching the heatmap path's `_sanitize_browserless_error`.
    """
    token = settings.LIGHTHOUSE_BROWSERLESS_TOKEN
    if token:
        text = text.replace(token, "[redacted]")
        text = text.replace(quote(token, safe=""), "[redacted]")
    return _TOKEN_QS_RE.sub(r"\1[redacted]", text)


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
    version = _as_text(report.get("lighthouseVersion"))
    element = _lcp_element(audits)
    if element is None:
        # Naming the element is the whole point of an audit, and the audit ids that carry it have
        # already been renamed once (Lighthouse 13 dropped the legacy set). Degrading quietly is
        # what let that go unnoticed, so a miss is logged with the version that produced it.
        logger.warning(
            "signals.lighthouse.no_lcp_element",
            lighthouse_version=version,
            audit_ids_present=sorted(audits)[:60],
        )
    return LighthouseAudit(
        requested_url=requested_url,
        final_url=final_url,
        form_factor=form_factor,
        lighthouse_version=version,
        performance_score=_performance_score(report),
        metrics=_metrics(audits),
        lcp_element=element,
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
    for audit_id in (*_LCP_INSIGHT_AUDITS, _LEGACY_LCP_ELEMENT_AUDIT):
        node = _first_node(audits.get(audit_id))
        if node is not None:
            return LcpElement(
                selector=_as_page_text(node.get("selector")),
                snippet=_as_page_text(node.get("snippet")),
                node_label=_as_page_text(node.get("nodeLabel")),
            )
    return None


def _first_node(audit: Any) -> dict[str, Any] | None:
    """The element node, wherever the running Lighthouse puts it.

    Insight audits list it as a `type: node` entry directly under `details.items`; the legacy
    element audit nested it under a `node` key, either on a top-level item or on a table row.
    All three are walked rather than pinning one shape.
    """
    if not isinstance(audit, dict):
        return None
    details = audit.get("details")
    if not isinstance(details, dict):
        return None
    for item in _iter_rows(details.get("items")):
        if item.get("type") == "node" and item.get("selector") is not None:
            return item
        node = item.get("node")
        if isinstance(node, dict):
            return node
        for nested in _iter_rows(item.get("items")):
            if isinstance(nested.get("node"), dict):
                return nested["node"]
    return None


def _iter_rows(items: Any) -> list[dict[str, Any]]:
    """Table rows as a list of dicts. A checklist keys its rows by name instead of listing
    them, so both are normalized here rather than at each call site."""
    if isinstance(items, list):
        return [row for row in items if isinstance(row, dict)]
    if isinstance(items, dict):
        return [{"_key": key, **row} for key, row in items.items() if isinstance(row, dict)]
    return []


def _lcp_phases(audits: dict[str, Any]) -> list[LcpPhase]:
    for audit_id in ("lcp-breakdown-insight", _LEGACY_LCP_ELEMENT_AUDIT):
        phases = _phases_from(audits.get(audit_id))
        if phases:
            return phases
    return []


def _phases_from(audit: Any) -> list[LcpPhase]:
    if not isinstance(audit, dict):
        return []
    details = audit.get("details")
    if not isinstance(details, dict):
        return []
    raw: list[tuple[str, float | None, str | None]] = []
    for item in _iter_rows(details.get("items")):
        for row in _iter_rows(item.get("items")):
            # Insight rows are {subpart, label, duration}; legacy rows are {phase, timing, percent}.
            label = _as_text(row.get("label")) or _as_text(row.get("phase"))
            if label is None:
                continue
            timing = row.get("duration") if "duration" in row else row.get("timing")
            raw.append(
                (
                    label,
                    round(float(timing), 3) if isinstance(timing, int | float) else None,
                    _as_text(row.get("percent")),
                )
            )
    # The subparts sum to LCP, so a share is well defined. Insight rows carry no `percent`, and a
    # phase breakdown is read as "where did the time go" — durations alone make the reader do the
    # division. Computed only from the rows present, never invented.
    total = sum(timing for _, timing, _ in raw if timing is not None)
    return [
        LcpPhase(
            phase=label,
            timing_ms=timing,
            percent=percent
            or (f"{round(100 * timing / total)}%" if percent is None and timing is not None and total else None),
        )
        for label, timing, percent in raw
    ]


def _failed_lcp_checks(audits: dict[str, Any]) -> list[AuditOpportunity]:
    failed: list[AuditOpportunity] = _checklist_failures(audits.get(_LCP_CHECKLIST_AUDIT))
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


def _checklist_failures(audit: Any) -> list[AuditOpportunity]:
    """Failing entries of an insight audit's checklist, e.g. `priorityHinted: false`."""
    if not isinstance(audit, dict):
        return []
    details = audit.get("details")
    if not isinstance(details, dict):
        return []
    failures: list[AuditOpportunity] = []
    for item in _iter_rows(details.get("items")):
        if not isinstance(item, dict) or item.get("type") != "checklist":
            continue
        for row in _iter_rows(item.get("items")):
            if row.get("value") is not False:
                continue
            key = _as_text(row.get("_key")) or "check"
            failures.append(
                AuditOpportunity(
                    audit_id=f"{_LCP_CHECKLIST_AUDIT}:{key}",
                    title=_as_text(row.get("label")) or key,
                    savings_ms=None,
                )
            )
    return failures


def _opportunities(audits: dict[str, Any]) -> list[AuditOpportunity]:
    found: list[AuditOpportunity] = []
    for audit_id, audit in audits.items():
        if not isinstance(audit, dict):
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
    found.sort(key=lambda entry: (-(entry.savings_ms or 0), entry.audit_id))
    return found[:MAX_OPPORTUNITIES]


def _savings_ms(audit: dict[str, Any]) -> float | None:
    """Estimated milliseconds this audit would save.

    Lighthouse 13 reports savings per metric on `metricSavings` and leaves `overallSavingsMs`
    at 0 on the few legacy opportunity audits that still carry it, so the per-metric map is
    read first and the legacy field is the fallback. `numericValue` is deliberately NOT a
    fallback: on most audits it is the measured value (bytes, element count, a duration that
    is not a saving), so treating it as a saving invents a number.
    """
    metric_savings = audit.get("metricSavings")
    if isinstance(metric_savings, dict):
        values = [
            float(metric_savings[key])
            for key in _TIME_METRIC_SAVINGS_KEYS
            if isinstance(metric_savings.get(key), int | float)
        ]
        if values and max(values) > 0:
            return round(max(values), 1)
    details = audit.get("details")
    if isinstance(details, dict):
        savings = details.get("overallSavingsMs")
        if isinstance(savings, int | float) and savings > 0:
            return round(float(savings), 1)
    return None


def _as_text(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def _as_page_text(value: Any) -> str | None:
    """Text lifted from the audited page's own markup, bounded before it reaches a scout.

    A selector, snippet, or alt text is page content, and the audited page is a CMS-driven site
    rather than something this repo controls. Lighthouse already truncates these, but the cap is
    theirs, not ours — bounding it here keeps one long attribute out of a prompt.
    """
    text = _as_text(value)
    if text is None:
        return None
    return text if len(text) <= MAX_PAGE_TEXT_LENGTH else text[:MAX_PAGE_TEXT_LENGTH] + "…"
