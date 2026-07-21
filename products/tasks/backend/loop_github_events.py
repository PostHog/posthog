"""GitHub event matching and firing for Loops.

The entry point is ``handle_github_event_for_loops``, registered as a handler in the
GitHub App webhook fan-out (``posthog.urls.github_webhook``) for the ``pull_request``,
``issues``, ``issue_comment`` and ``push`` events. Called after signature verification
and JSON parsing, alongside the other webhook consumers.
"""

import time
from typing import Any, Literal

import structlog
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.redis import get_client

from products.tasks.backend.logic.services import loop_runs
from products.tasks.backend.models import LoopTrigger

logger = structlog.get_logger(__name__)

_EXCERPT_LIMIT = 500
_SELF_TRIGGER_BRANCH_PREFIX = "loop/"

# Request-level flood control ahead of the per-loop/team rate caps: those bound dispatched runs,
# not the matching work or the fire/notification records a sustained stream of unique deliveries
# would otherwise write. Sized well above a busy repo's real event volume.
_EVENT_THROTTLE_LIMIT = 300
_EVENT_THROTTLE_WINDOW_SECONDS = 300

LoopGithubEventOutcome = Literal["matched", "deduped", "skipped", "throttled", "fired", "error"]

LOOP_GITHUB_EVENT_TOTAL = Counter(
    "posthog_tasks_loop_github_event_total",
    "GitHub webhook matching/firing decisions for Loops, keyed by outcome",
    labelnames=["outcome"],
)


def _observe_github_event(outcome: LoopGithubEventOutcome) -> None:
    LOOP_GITHUB_EVENT_TOTAL.labels(outcome=outcome).inc()


def handle_github_event_for_loops(event_type: str, payload: dict[str, Any], delivery_id: str) -> None:
    if _is_self_triggered_branch(event_type, payload):
        logger.info("loop_github_event_self_trigger_excluded", event_type=event_type, delivery_id=delivery_id)
        _observe_github_event("skipped")
        return

    installation_id = _extract_installation_id(payload)
    if installation_id is None:
        logger.warning("loop_github_event_no_installation", event_type=event_type, delivery_id=delivery_id)
        _observe_github_event("skipped")
        return

    repository_full_name = ((payload.get("repository") or {}).get("full_name") or "").strip()
    if not repository_full_name:
        logger.warning("loop_github_event_no_repository", event_type=event_type, delivery_id=delivery_id)
        _observe_github_event("skipped")
        return

    # A matched trigger fires an unattended run with the loop owner's GitHub/MCP credentials, and the
    # event's issue/comment/PR text is fed into that run's prompt. Restrict firing to trusted GitHub
    # actors so untrusted external content can't steer a credentialed run: a "data, not instructions"
    # fence is not an enforcement boundary (see loop_github_events untrusted-content review).
    if not _event_actor_is_trusted(event_type, payload):
        logger.info("loop_github_event_untrusted_actor_excluded", event_type=event_type, delivery_id=delivery_id)
        _observe_github_event("skipped")
        return

    # After the trusted-actor check on purpose: only events that could actually fire consume the
    # budget, so untrusted external activity can't starve a repo's legitimate trigger fires.
    if _github_events_throttled(installation_id, repository_full_name):
        logger.warning(
            "loop_github_event_throttled",
            event_type=event_type,
            delivery_id=delivery_id,
            repository=repository_full_name,
        )
        _observe_github_event("throttled")
        return

    action = payload.get("action")
    summary = _build_event_summary(event_type, payload)

    matched = 0
    for integration in Integration.objects.filter(kind="github", integration_id=installation_id):
        matched += _match_and_fire_for_integration(
            integration, repository_full_name, event_type, action, payload, delivery_id, summary
        )

    logger.info(
        "loop_github_event_matched",
        event_type=event_type,
        action=action,
        delivery_id=delivery_id,
        repository=repository_full_name,
        matched_triggers=matched,
    )


def _match_and_fire_for_integration(
    integration: Integration,
    repository_full_name: str,
    event_type: str,
    action: str | None,
    payload: dict[str, Any],
    delivery_id: str,
    summary: dict[str, Any],
) -> int:
    """Match and fire triggers for one team's integration, isolated from other teams.

    A lookup failure for one team (e.g. a stale team reference) must not stop the
    same delivery from firing loops for every other team sharing the installation.
    """
    try:
        triggers = (
            LoopTrigger.objects.for_team(integration.team_id)
            .filter(
                type=LoopTrigger.TriggerType.GITHUB,
                enabled=True,
                loop__enabled=True,
                loop__deleted=False,
                github_integration_id=integration.id,
                repository__iexact=repository_full_name,
                event_types__contains=[event_type],
            )
            .select_related("loop")
        )
    except Exception as e:
        logger.exception("loop_github_event_team_lookup_failed", team_id=integration.team_id, delivery_id=delivery_id)
        capture_exception(e)
        _observe_github_event("error")
        return 0

    matched = 0
    for trigger in triggers:
        if not _trigger_filters_match(trigger, action, payload):
            continue

        matched += 1
        _observe_github_event("matched")
        _fire_matched_trigger(trigger, delivery_id, summary)

    return matched


def _fire_matched_trigger(trigger: LoopTrigger, delivery_id: str, summary: dict[str, Any]) -> None:
    try:
        trigger_context = loop_runs.render_trigger_context("github", summary, trigger.loop)
        result = loop_runs.fire_loop(
            loop=trigger.loop,
            trigger=trigger,
            fire_key=delivery_id,
            trigger_context=trigger_context,
        )
        _observe_github_event(_fire_result_outcome(result.reason))
    except Exception as e:
        logger.exception("loop_github_event_fire_failed", trigger_id=str(trigger.id), delivery_id=delivery_id)
        capture_exception(e)
        _observe_github_event("error")


def _fire_result_outcome(reason: str) -> LoopGithubEventOutcome:
    if reason == "created":
        return "fired"
    if reason == "deduped":
        return "deduped"
    return "skipped"


def _github_events_throttled(installation_id: str, repository_full_name: str) -> bool:
    """Fixed-window counter per (installation, repository), keyed on the window bucket so a missed
    expiry can never wedge the throttle shut. Fails open: a Redis outage must not drop fires."""
    try:
        client = get_client()
        bucket = int(time.time() // _EVENT_THROTTLE_WINDOW_SECONDS)
        key = f"loop_github_events:throttle:{installation_id}:{repository_full_name.lower()}:{bucket}"
        count = client.incr(key)
        if count == 1:
            client.expire(key, _EVENT_THROTTLE_WINDOW_SECONDS * 2)
        return count > _EVENT_THROTTLE_LIMIT
    except Exception:
        logger.warning("loop_github_event_throttle_check_failed", installation_id=installation_id, exc_info=True)
        return False


def _extract_installation_id(payload: dict[str, Any]) -> str | None:
    installation_id = (payload.get("installation") or {}).get("id")
    return str(installation_id) if installation_id is not None else None


# GitHub `author_association` values that mean the actor has a trusted relationship to the repo.
# OWNER/MEMBER/COLLABORATOR have (or are granted) write-ish access; external CONTRIBUTOR / NONE /
# FIRST_TIME_CONTRIBUTOR do not and must not be able to steer a credentialed run.
_TRUSTED_GITHUB_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def _event_actor_is_trusted(event_type: str, payload: dict[str, Any]) -> bool:
    """Whether the event's author is a trusted repo actor, read from the webhook's `author_association`
    (no API call). Push events are inherently write-gated (you can't push without access), so they are
    trusted. For issue / comment / PR events the triggering author's association decides; an absent or
    external association is untrusted (fail closed)."""
    if event_type == "push":
        return True
    for key in ("comment", "issue", "pull_request"):
        node = payload.get(key)
        if isinstance(node, dict) and node.get("author_association") is not None:
            return str(node.get("author_association")).upper() in _TRUSTED_GITHUB_ASSOCIATIONS
    return False


def _is_self_triggered_branch(event_type: str, payload: dict[str, Any]) -> bool:
    if event_type == "push":
        ref = payload.get("ref") or ""
        return isinstance(ref, str) and ref.startswith(f"refs/heads/{_SELF_TRIGGER_BRANCH_PREFIX}")

    if event_type == "pull_request":
        head_ref = ((payload.get("pull_request") or {}).get("head") or {}).get("ref") or ""
        return isinstance(head_ref, str) and head_ref.startswith(_SELF_TRIGGER_BRANCH_PREFIX)

    return False


def _trigger_filters_match(trigger: LoopTrigger, action: str | None, payload: dict[str, Any]) -> bool:
    """JSON `filters` evaluated last, after the DB query already matched the promoted
    `(github_integration_id, repository, event_types)` columns (see LOOPS.md "GitHub event
    triggers: infrastructure changes")."""
    config = trigger.config if isinstance(trigger.config, dict) else {}
    filters = config.get("filters")
    return _filters_match(filters if isinstance(filters, dict) else {}, action, payload)


def _filters_match(filters: dict[str, Any], action: str | None, payload: dict[str, Any]) -> bool:
    allowed_actions = filters.get("actions")
    if allowed_actions and action not in allowed_actions:
        return False

    allowed_branches = filters.get("branches")
    if allowed_branches and not _branch_matches(allowed_branches, payload):
        return False

    allowed_labels = filters.get("labels")
    if allowed_labels and not _labels_match(allowed_labels, payload):
        return False

    return True


def _event_branch(payload: dict[str, Any]) -> str | None:
    ref = payload.get("ref")
    if isinstance(ref, str) and ref.startswith("refs/heads/"):
        return ref[len("refs/heads/") :]

    pull_request = payload.get("pull_request")
    if isinstance(pull_request, dict):
        base_ref = (pull_request.get("base") or {}).get("ref")
        if isinstance(base_ref, str):
            return base_ref

    return None


def _branch_matches(allowed_branches: list[Any], payload: dict[str, Any]) -> bool:
    branch = _event_branch(payload)
    return branch is not None and branch in allowed_branches


def _event_labels(payload: dict[str, Any]) -> set[str]:
    target = payload.get("pull_request") or payload.get("issue") or {}
    labels = target.get("labels") if isinstance(target, dict) else None
    if not isinstance(labels, list):
        return set()
    return {label["name"] for label in labels if isinstance(label, dict) and label.get("name")}


def _labels_match(allowed_labels: list[Any], payload: dict[str, Any]) -> bool:
    return bool(_event_labels(payload).intersection(allowed_labels))


def _excerpt(text: Any, limit: int = _EXCERPT_LIMIT) -> str | None:
    if not isinstance(text, str):
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _build_event_summary(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Compact, agent-safe summary of a webhook payload for trigger_context rendering.

    Raw GitHub payloads can be large and noisy; only the fields useful as run context
    are kept, with free-text fields excerpted.
    """
    summary: dict[str, Any] = {
        "event": event_type,
        "action": payload.get("action"),
        "repository": (payload.get("repository") or {}).get("full_name"),
        "sender": (payload.get("sender") or {}).get("login"),
    }

    pull_request = payload.get("pull_request")
    if isinstance(pull_request, dict):
        summary["pull_request"] = {
            "number": pull_request.get("number"),
            "title": pull_request.get("title"),
            "body": _excerpt(pull_request.get("body")),
            "html_url": pull_request.get("html_url"),
            "head_ref": (pull_request.get("head") or {}).get("ref"),
            "base_ref": (pull_request.get("base") or {}).get("ref"),
        }

    issue = payload.get("issue")
    if isinstance(issue, dict):
        summary["issue"] = {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "body": _excerpt(issue.get("body")),
            "html_url": issue.get("html_url"),
        }

    comment = payload.get("comment")
    if isinstance(comment, dict):
        summary["comment"] = {
            "body": _excerpt(comment.get("body")),
            "html_url": comment.get("html_url"),
        }

    if event_type == "push":
        summary["ref"] = payload.get("ref")
        commits = payload.get("commits")
        if isinstance(commits, list):
            # Commit messages are free text an external contributor can author (e.g. a squash-merged
            # PR title), so a trusted pusher merging them would otherwise inject attacker-controlled
            # text into the credentialed run. Keep only the non-free-text commit id, not the message.
            summary["commits"] = [{"id": commit.get("id")} for commit in commits if isinstance(commit, dict)][:10]

    return summary


__all__ = ["handle_github_event_for_loops"]
