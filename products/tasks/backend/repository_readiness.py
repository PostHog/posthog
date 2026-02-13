import re
import time
import base64
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone

import requests

from posthog.models.event_definition import EventDefinition
from posthog.models.integration import GitHubIntegration, Integration

from products.error_tracking.backend.models import ErrorTrackingIssue
from products.tasks.backend.models import Task

logger = logging.getLogger(__name__)

READINESS_CACHE_VERSION = 2
READINESS_CACHE_TTL_SECONDS = 10 * 60
DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 30
MAX_FILES_TO_SCAN = 20
MAX_CANDIDATE_PATHS = 80
SCAN_TIME_BUDGET_SECONDS = 30
GITHUB_REQUEST_TIMEOUT_SECONDS = 5

REPO_NAME_TEST_HINTS = (
    "test",
    "sandbox",
    "demo",
    "example",
    "fixture",
    "playground",
)
REPO_NAME_SDK_HINTS = ("sdk", "client", "library", "lib")
REPO_NAME_FRONTEND_HINTS = ("web", "frontend", "site", "app", "js")
REPO_NAME_BACKEND_HINTS = ("backend", "server", "api", "infra", "monorepo")

FRONTEND_FILE_MARKERS = {
    "package.json",
    "next.config.js",
    "next.config.ts",
    "vite.config.js",
    "vite.config.ts",
    "nuxt.config.js",
    "nuxt.config.ts",
}
BACKEND_FILE_MARKERS = {
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
}

SCANNABLE_EXTENSIONS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".py",
    ".go",
    ".java",
    ".rb",
    ".php",
    ".cs",
)
IGNORED_PATH_PREFIXES = (
    "node_modules/",
    "dist/",
    "build/",
    "coverage/",
    ".next/",
    "vendor/",
)

POSTHOG_INIT_PATTERN = re.compile(r"posthog\.init\s*\(", re.IGNORECASE)
POSTHOG_CAPTURE_PATTERN = re.compile(r"posthog\.capture\s*\(", re.IGNORECASE)
POSTHOG_CAPTURE_EVENT_PATTERN = re.compile(r'posthog\.capture\s*\(\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
ERROR_SIGNAL_PATTERNS = (
    re.compile(r"posthog\.captureexception\s*\(", re.IGNORECASE),
    re.compile(r"sentry\.init\s*\(", re.IGNORECASE),
    re.compile(r"capture_exception\s*\(", re.IGNORECASE),
    re.compile(r"reportexception\s*\(", re.IGNORECASE),
)


@dataclass
class RepositoryScanEvidence:
    found_posthog_init: bool
    found_posthog_capture: bool
    found_error_signal: bool
    captured_event_names: list[str]
    files_scanned: int
    detected_files_count: int
    frontend_markers: int
    backend_markers: int


def _normalize_repo_key(repository: str) -> str:
    return repository.strip().lower()


def _cache_key(*, team_id: int, integration_id: int, repository: str, window_days: int) -> str:
    return (
        f"tasks_repo_readiness:v{READINESS_CACHE_VERSION}:"
        f"team:{team_id}:integration:{integration_id}:repo:{repository}:window:{window_days}"
    )


def _refresh_installation_token(integration: Integration) -> None:
    github = GitHubIntegration(integration)
    try:
        if github.access_token_expired():
            github.refresh_access_token()
            integration.refresh_from_db(fields=["config", "sensitive_config"])
    except Exception:
        logger.warning("repository_readiness.refresh_token_failed", exc_info=True)
        return


def _github_get(access_token: str, path: str, params: dict[str, Any] | None = None) -> requests.Response:
    url = f"https://api.github.com{path}"
    return requests.get(
        url,
        params=params,
        timeout=GITHUB_REQUEST_TIMEOUT_SECONDS,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _fetch_repository_tree(access_token: str, repository: str) -> tuple[list[str], str | None]:
    repo_response = _github_get(access_token, f"/repos/{repository}")
    if repo_response.status_code != 200:
        return [], None

    repo_data = repo_response.json()
    default_branch = repo_data.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        return [], None

    tree_response = _github_get(
        access_token,
        f"/repos/{repository}/git/trees/{default_branch}",
        params={"recursive": 1},
    )
    if tree_response.status_code != 200:
        return [], default_branch

    tree_data = tree_response.json()
    paths: list[str] = []
    for entry in tree_data.get("tree", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "blob":
            continue
        path = entry.get("path")
        if isinstance(path, str):
            paths.append(path)

    return paths, default_branch


def _should_scan_path(path: str) -> bool:
    lowered = path.lower()
    if lowered.endswith(".min.js"):
        return False
    if any(lowered.startswith(prefix) for prefix in IGNORED_PATH_PREFIXES):
        return False
    return lowered.endswith(SCANNABLE_EXTENSIONS)


def _candidate_path_score(path: str) -> int:
    lowered = path.lower()
    score = 0
    for keyword in ("posthog", "analytics", "tracking", "telemetry", "instrument", "error", "replay"):
        if keyword in lowered:
            score += 2
    if lowered.startswith("src/"):
        score += 1
    if lowered.startswith("app/"):
        score += 1
    return score


def _select_candidate_paths(paths: list[str]) -> list[str]:
    candidates = [path for path in paths if _should_scan_path(path)]
    candidates.sort(key=lambda p: (_candidate_path_score(p), -len(p)), reverse=True)
    return candidates[:MAX_CANDIDATE_PATHS]


def _fetch_file_content(access_token: str, repository: str, path: str, ref: str | None) -> str | None:
    response = _github_get(access_token, f"/repos/{repository}/contents/{path}", params={"ref": ref} if ref else None)
    if response.status_code != 200:
        return None

    payload = response.json()
    if not isinstance(payload, dict):
        return None

    content = payload.get("content")
    encoding = payload.get("encoding")
    if not isinstance(content, str) or encoding != "base64":
        return None

    try:
        return base64.b64decode(content).decode("utf-8", errors="ignore")
    except Exception:
        return None


def _scan_repository(access_token: str, repository: str) -> tuple[RepositoryScanEvidence, list[str]]:
    tree_paths, default_branch = _fetch_repository_tree(access_token, repository)

    found_posthog_init = False
    found_posthog_capture = False
    found_error_signal = False
    event_names: set[str] = set()
    scanned = 0

    start = time.monotonic()
    candidate_paths = _select_candidate_paths(tree_paths)
    for path in candidate_paths[:MAX_FILES_TO_SCAN]:
        if time.monotonic() - start > SCAN_TIME_BUDGET_SECONDS:
            logger.warning(
                "repository_readiness.scan_time_budget_exceeded",
                extra={"repository": repository, "scanned": scanned},
            )
            break
        content = _fetch_file_content(access_token, repository, path, default_branch)
        if content is None:
            continue

        scanned += 1
        if POSTHOG_INIT_PATTERN.search(content):
            found_posthog_init = True
        if POSTHOG_CAPTURE_PATTERN.search(content):
            found_posthog_capture = True
        for pattern in ERROR_SIGNAL_PATTERNS:
            if pattern.search(content):
                found_error_signal = True
                break

        for match in POSTHOG_CAPTURE_EVENT_PATTERN.findall(content):
            cleaned = match.strip()
            if cleaned:
                event_names.add(cleaned)

    frontend_markers = 0
    backend_markers = 0
    for path in tree_paths:
        filename = path.rsplit("/", 1)[-1]
        if filename in FRONTEND_FILE_MARKERS:
            frontend_markers += 1
        if filename in BACKEND_FILE_MARKERS:
            backend_markers += 1

    evidence = RepositoryScanEvidence(
        found_posthog_init=found_posthog_init,
        found_posthog_capture=found_posthog_capture,
        found_error_signal=found_error_signal,
        captured_event_names=sorted(event_names)[:100],
        files_scanned=scanned,
        detected_files_count=len(candidate_paths),
        frontend_markers=frontend_markers,
        backend_markers=backend_markers,
    )
    return evidence, tree_paths


def _classify_repository(repository: str, tree_paths: list[str], evidence: RepositoryScanEvidence) -> tuple[str, bool]:
    repo_name = repository.split("/")[-1].lower()

    if any(hint in repo_name for hint in REPO_NAME_TEST_HINTS):
        return "test_or_sandbox", True
    if any(hint in repo_name for hint in REPO_NAME_SDK_HINTS):
        return "sdk_or_library", True

    if evidence.frontend_markers > evidence.backend_markers and evidence.frontend_markers > 0:
        return "frontend_js", False
    if evidence.backend_markers > evidence.frontend_markers and evidence.backend_markers > 0:
        return "backend_service", False

    if any(hint in repo_name for hint in REPO_NAME_FRONTEND_HINTS):
        return "frontend_js", False
    if any(hint in repo_name for hint in REPO_NAME_BACKEND_HINTS):
        return "backend_service", False

    if any(path.endswith((".tsx", ".jsx")) for path in tree_paths):
        return "frontend_js", False
    if any(path.endswith((".py", ".go", ".java", ".rs")) for path in tree_paths):
        return "backend_service", False

    return "unknown", False


def _capability_state(reason: str, state: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "estimated": True,
        "reason": reason,
        "evidence": evidence or {},
    }


def _applicable_capabilities(classification: str, excluded: bool) -> dict[str, bool]:
    if excluded:
        return {
            "tracking": False,
            "computer_vision": False,
            "errors": False,
        }

    if classification == "frontend_js":
        return {
            "tracking": True,
            "computer_vision": True,
            "errors": True,
        }

    if classification == "backend_service":
        return {
            "tracking": True,
            "computer_vision": False,
            "errors": True,
        }

    if classification == "unknown":
        return {
            "tracking": True,
            "computer_vision": False,
            "errors": True,
        }

    # Defensive fallback for any unhandled classification
    return {
        "tracking": False,
        "computer_vision": False,
        "errors": False,
    }


def compute_repository_readiness(
    *,
    team: Any,
    repository: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    refresh: bool = False,
) -> dict[str, Any]:
    repository = _normalize_repo_key(repository)
    window_days = min(max(window_days, 1), MAX_WINDOW_DAYS)

    integration = Integration.objects.filter(team=team, kind="github").first()
    if not integration:
        not_ready = _capability_state("GitHub integration is not connected.", "needs_setup")
        return {
            "repository": repository,
            "classification": "unknown",
            "excluded": False,
            "coreSuggestions": not_ready,
            "replayInsights": not_ready,
            "errorInsights": not_ready,
            "overall": "needs_setup",
            "evidenceTaskCount": 0,
            "windowDays": window_days,
            "generatedAt": timezone.now().isoformat(),
            "cacheAgeSeconds": 0,
        }

    key = _cache_key(team_id=team.id, integration_id=integration.id, repository=repository, window_days=window_days)
    if not refresh:
        cached = cache.get(key)
        if isinstance(cached, dict):
            generated_at_str = cached.get("generatedAt")
            if generated_at_str:
                try:
                    generated_at_dt = datetime.fromisoformat(generated_at_str)
                    if generated_at_dt.tzinfo is None:
                        generated_at_dt = generated_at_dt.replace(tzinfo=UTC)
                    age_seconds = max(0, int((timezone.now() - generated_at_dt).total_seconds()))
                    return {**cached, "cacheAgeSeconds": age_seconds}
                except (ValueError, TypeError):
                    pass
            return cached

    _refresh_installation_token(integration)
    access_token = integration.sensitive_config.get("access_token") if integration.sensitive_config else None

    if not isinstance(access_token, str) or not access_token:
        unavailable = _capability_state("Unable to access GitHub integration token.", "unknown")
        response = {
            "repository": repository,
            "classification": "unknown",
            "excluded": False,
            "coreSuggestions": unavailable,
            "replayInsights": unavailable,
            "errorInsights": unavailable,
            "overall": "unknown",
            "evidenceTaskCount": 0,
            "windowDays": window_days,
            "generatedAt": timezone.now().isoformat(),
            "cacheAgeSeconds": 0,
        }
        cache.set(key, response, READINESS_CACHE_TTL_SECONDS)
        return response

    try:
        scan_evidence, tree_paths = _scan_repository(access_token, repository)
    except Exception:
        logger.exception("repository_readiness.scan_failed", extra={"repository": repository})
        scan_evidence = RepositoryScanEvidence(
            found_posthog_init=False,
            found_posthog_capture=False,
            found_error_signal=False,
            captured_event_names=[],
            files_scanned=0,
            detected_files_count=0,
            frontend_markers=0,
            backend_markers=0,
        )
        tree_paths = []
    classification, excluded = _classify_repository(repository, tree_paths, scan_evidence)
    applicability = _applicable_capabilities(classification, excluded)

    since = timezone.now() - timedelta(days=window_days)
    team_events = EventDefinition.objects.filter(team=team)

    recent_tracking_events = 0
    if scan_evidence.captured_event_names:
        recent_tracking_events = team_events.filter(
            name__in=scan_evidence.captured_event_names,
            last_seen_at__gte=since,
        ).count()

    replay_task_count = Task.objects.filter(
        team=team,
        origin_product=Task.OriginProduct.SESSION_SUMMARIES,
        repository__iexact=repository,
        created_at__gte=since,
        deleted=False,
    ).count()

    # Team-scoped intentionally: ErrorTrackingIssue has no repository field
    error_issue_count = ErrorTrackingIssue.objects.filter(team=team, created_at__gte=since).count()

    # Tracking
    if not applicability["tracking"]:
        tracking = _capability_state("Tracking is not required for this repository type.", "not_applicable")
    else:
        static_tracking_ok = scan_evidence.found_posthog_init and (
            scan_evidence.found_posthog_capture or bool(scan_evidence.captured_event_names)
        )
        if not static_tracking_ok:
            tracking = _capability_state(
                "No reliable tracking instrumentation found in repository code.",
                "needs_setup",
                evidence={"matchedEventCount": recent_tracking_events},
            )
        elif not team.proactive_tasks_enabled:
            tracking = _capability_state(
                "Tracking instrumentation detected. Enable proactive tasks for this project.",
                "detected",
                evidence={"matchedEventCount": recent_tracking_events},
            )
        elif recent_tracking_events > 0:
            tracking = _capability_state(
                "Tracking instrumentation detected and matching events were seen recently.",
                "ready",
                evidence={
                    "matchedEventCount": recent_tracking_events,
                    "eventNameCount": len(scan_evidence.captured_event_names),
                },
            )
        else:
            tracking = _capability_state(
                "Tracking instrumentation detected, but waiting for matching event data in this project.",
                "waiting_for_data",
                evidence={"matchedEventCount": recent_tracking_events},
            )

    # Computer vision (session replay)
    if not applicability["computer_vision"]:
        computer_vision = _capability_state(
            "Computer vision is not applicable for this repository type.",
            "not_applicable",
        )
    else:
        static_cv_ok = scan_evidence.found_posthog_init
        if not static_cv_ok:
            computer_vision = _capability_state(
                "No frontend PostHog initialization found for computer vision support.",
                "needs_setup",
                evidence={"replayTaskCount": replay_task_count},
            )
        elif not team.session_recording_opt_in:
            computer_vision = _capability_state(
                "PostHog SDK detected. Enable session replay for this project.",
                "detected",
                evidence={"replayTaskCount": replay_task_count},
            )
        elif replay_task_count > 0:
            computer_vision = _capability_state(
                "Computer vision is configured and replay-derived evidence exists.",
                "ready",
                evidence={"replayTaskCount": replay_task_count},
            )
        else:
            computer_vision = _capability_state(
                "Computer vision is configured, waiting for replay-derived evidence.",
                "waiting_for_data",
                evidence={"replayTaskCount": replay_task_count},
            )

    # Errors
    if not applicability["errors"]:
        errors = _capability_state("Error tracking is not required for this repository type.", "not_applicable")
    else:
        static_error_ok = scan_evidence.found_error_signal or (
            classification == "frontend_js" and scan_evidence.found_posthog_init
        )
        if not static_error_ok:
            errors = _capability_state(
                "No reliable error instrumentation found in repository code.",
                "needs_setup",
                evidence={"recentErrorIssueCount": error_issue_count},
            )
        elif not team.autocapture_exceptions_opt_in:
            errors = _capability_state(
                "Error instrumentation detected. Enable error tracking for this project.",
                "detected",
                evidence={"recentErrorIssueCount": error_issue_count},
            )
        elif error_issue_count > 0:
            errors = _capability_state(
                "Error instrumentation detected and recent error data exists.",
                "ready",
                evidence={"recentErrorIssueCount": error_issue_count},
            )
        else:
            errors = _capability_state(
                "Error instrumentation detected, but waiting for error data in this project.",
                "waiting_for_data",
                evidence={"recentErrorIssueCount": error_issue_count},
            )

    applicable_states = [
        capability["state"]
        for capability in (tracking, computer_vision, errors)
        if capability["state"] != "not_applicable"
    ]

    if not applicable_states:
        overall = "unknown"
    elif all(state == "ready" for state in applicable_states):
        overall = "ready"
    elif all(state in ("needs_setup", "detected") for state in applicable_states):
        overall = "needs_setup" if all(state == "needs_setup" for state in applicable_states) else "detected"
    elif any(state == "unknown" for state in applicable_states):
        overall = "unknown"
    else:
        overall = "partial"

    generated_at = timezone.now()
    response = {
        "repository": repository,
        "classification": classification,
        "excluded": excluded,
        "coreSuggestions": tracking,
        "replayInsights": computer_vision,
        "errorInsights": errors,
        "overall": overall,
        "evidenceTaskCount": replay_task_count,
        "windowDays": window_days,
        "generatedAt": generated_at.isoformat(),
        "cacheAgeSeconds": 0,
        "scan": {
            "filesScanned": scan_evidence.files_scanned,
            "detectedFilesCount": scan_evidence.detected_files_count,
            "eventNameCount": len(scan_evidence.captured_event_names),
            "foundPosthogInit": scan_evidence.found_posthog_init,
            "foundPosthogCapture": scan_evidence.found_posthog_capture,
            "foundErrorSignal": scan_evidence.found_error_signal,
        },
    }

    cache.set(key, response, READINESS_CACHE_TTL_SECONDS)
    return response
