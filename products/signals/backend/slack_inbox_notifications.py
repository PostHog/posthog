"""Slack notifications for signals inbox items.

Mirrors the inbox Reports tab's actionability gate: a report notifies only if it's actionable
(its latest actionability judgment is immediately_actionable or requires_human_input) — READY is
enforced upstream — and has at least one suggested reviewer that resolves to a destination.
Each reviewer is routed to one channel: their own configured channel if set (filtered by their
min-priority), otherwise the team-default channel. Reviewers sharing a channel get a single post
mentioning only the reviewers routed there. When no suggested reviewer resolves, the report is
still delivered to the team-default channel (if one is configured) with no mentions, so a team is
notified even when none of its members are linked to a resolvable GitHub identity.
All sends are best-effort.
"""

from __future__ import annotations

import re
import json
import logging

from django.conf import settings

from markdown_to_mrkdwn import SlackMarkdownConverter
from slack_sdk.errors import SlackApiError

from posthog.models import User
from posthog.models.integration import Integration, SlackIntegration

from products.signals.backend.enums import SIGNAL_SOURCE_PRODUCT_LABELS
from products.signals.backend.implementation_pr import fetch_implementation_pr_urls_for_reports
from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.report_generation.resolve_reviewers import (
    enrich_reviewer_dicts_with_org_members,
    normalized_github_logins_from_suggested_reviewer_artefacts,
    resolve_org_github_login_to_users,
)

# Actionability values shown in the inbox Reports tab. Slack notifications mirror that tab, so a
# report notifies iff its latest actionability judgment is one of these (and it's READY).
_ACTIONABLE_VALUES = frozenset(
    {ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value, ActionabilityChoice.REQUIRES_HUMAN_INPUT.value}
)

logger = logging.getLogger(__name__)

_SLACK_MRKDWN_CONVERTER = SlackMarkdownConverter()

_SUMMARY_EXCERPT_MAX_LEN = 600
_SLACK_HEADER_MAX_LEN = 150
# Bound message size / avoid pinging a crowd.
_MAX_REVIEWER_MENTIONS = 5

# Deep link opened by the PostHog Code desktop app. Override via env for dev (`posthog-code-dev`).
POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME = getattr(settings, "POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME", "posthog-code")

# Wire contract with products/slack_app/backend/api.py — keep this action_id in sync.
SIGNALS_DISMISS_REPORT_ACTION_ID = "signals_dismiss_report"

# Priority ranking — lower index is higher priority. Index used for threshold comparison.
_PRIORITY_ORDER: tuple[str, ...] = (
    AutonomyPriority.P0,
    AutonomyPriority.P1,
    AutonomyPriority.P2,
    AutonomyPriority.P3,
    AutonomyPriority.P4,
)

# Only the two highest priorities get a red, alarming emoji; the rest use a calmer severity gradient.
_SLACK_PRIORITY_LABELS: dict[str, str] = {
    AutonomyPriority.P0: "‼️ P0",
    AutonomyPriority.P1: "❗ P1",
    AutonomyPriority.P2: "🟠 P2",
    AutonomyPriority.P3: "🟡 P3",
    AutonomyPriority.P4: "🔵 P4",
}

_SOURCE_PRODUCT_LABELS: dict[str, str] = {
    product.value: label for product, label in SIGNAL_SOURCE_PRODUCT_LABELS.items()
}


def _priority_rank(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return _PRIORITY_ORDER.index(value)
    except ValueError:
        return None


def _slack_priority_label(value: str) -> str:
    return _SLACK_PRIORITY_LABELS.get(value, value)


def _meets_min_priority(report_priority: str | None, min_priority: str | None) -> bool:
    """Whether a report with the given priority meets the user's min-priority threshold.

    `min_priority=None` notifies for every report with a recognised priority.
    Missing or unrecognised report priorities do not notify because Slack
    notifications only go out once actionability and priority are persisted.
    """
    report_rank = _priority_rank(report_priority)
    if report_rank is None:
        return False
    if min_priority is None:
        return True
    min_rank = _priority_rank(min_priority)
    if min_rank is None:
        return True
    # Lower index = higher priority (P0 < P4).
    return report_rank <= min_rank


def _report_repository(report: SignalReport) -> str | None:
    """The repository the report's research selected, from the latest repo_selection artefact."""
    art = report.artefacts.filter(type=SignalReportArtefact.ArtefactType.REPO_SELECTION).order_by("-created_at").first()
    if art is None:
        return None
    try:
        data = json.loads(art.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    repo = data.get("repository")
    return repo.strip() if isinstance(repo, str) and repo.strip() else None


def _latest_priority(report: SignalReport) -> str | None:
    art = (
        report.artefacts.filter(type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT)
        .order_by("-created_at")
        .first()
    )
    if art is None:
        return None
    try:
        data = json.loads(art.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("priority")
    return value if isinstance(value, str) else None


def _latest_actionability(report: SignalReport) -> str | None:
    art = (
        report.artefacts.filter(type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT)
        .order_by("-created_at")
        .first()
    )
    if art is None:
        return None
    try:
        data = json.loads(art.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("actionability")
    return value if isinstance(value, str) else None


def _resolve_suggested_reviewer_user_ids(report: SignalReport) -> set[int]:
    """Resolve the suggested-reviewer GitHub logins on the report to PostHog user IDs.

    Uses the same enrichment path the API uses so a user that connected their
    GitHub account after the report was generated is still picked up.
    """
    artefacts = list(
        report.artefacts.filter(
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        ).order_by("-created_at")
    )
    if not artefacts:
        return set()

    logins = normalized_github_logins_from_suggested_reviewer_artefacts(artefacts)
    if not logins:
        return set()
    login_map = resolve_org_github_login_to_users(report.team_id, logins)
    if not login_map:
        return set()

    # Enrich each artefact's payload to drop reviewers that didn't resolve to a user.
    resolved_user_ids: set[int] = set()
    for art in artefacts:
        try:
            parsed = json.loads(art.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed, list):
            continue
        enriched = enrich_reviewer_dicts_with_org_members(report.team_id, parsed, login_to_user=login_map)
        for entry in enriched:
            user = entry.get("user") if isinstance(entry, dict) else None
            if isinstance(user, dict) and user.get("id"):
                resolved_user_ids.add(int(user["id"]))
    return resolved_user_ids


def _own_channel_configs_by_user(team_id: int, user_ids: set[int]) -> dict[int, SignalUserAutonomyConfig]:
    """Per-user configs that name an own Slack channel on this team's integration.

    A reviewer absent from this map has no own channel and falls back to the team default.
    """
    configs = (
        SignalUserAutonomyConfig.objects.filter(user_id__in=user_ids)
        .filter(slack_notification_integration__team_id=team_id)
        .exclude(slack_notification_channel__isnull=True)
        .exclude(slack_notification_channel="")
        .select_related("slack_notification_integration")
    )
    return {config.user_id: config for config in configs}


def _get_team_slack_integration(team_id: int) -> Integration | None:
    # Standard `slack` kind (not `slack-posthog-code`), matching the per-user path.
    return Integration.objects.filter(team_id=team_id, kind="slack").first()


def _team_notification_channel(team_id: int) -> str | None:
    config = SignalTeamConfig.objects.filter(team_id=team_id).only("default_slack_notification_channel").first()
    if config is None:
        return None
    channel = (config.default_slack_notification_channel or "").strip()
    return channel or None


def _channel_id_from_target(value: str) -> str:
    """Mirror `getSlackChannelIdFromTargetValue` in the frontend."""
    return value.split("|", 1)[0].strip()


def _channel_display_name(value: str) -> str:
    pipe = value.find("|")
    if pipe == -1:
        return value
    return value[pipe + 1 :].strip() or value[:pipe].strip()


def _posthog_user_display_name(user: User) -> str:
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(part for part in parts if part).strip()
    if name:
        return name
    email = (user.email or "").strip()
    if "@" in email:
        return email.split("@", 1)[0]
    return email or "Unknown user"


def lookup_slack_user_id_by_email(slack: SlackIntegration, email: str) -> str | None:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return None

    try:
        response = slack.client.users_lookupByEmail(email=normalized_email)
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        if error_code != "users_not_found":
            logger.warning(
                "signals_inbox_slack_user_email_lookup_failed",
                extra={"email": normalized_email, "error": error_code},
            )
        return None

    data = response.data if hasattr(response, "data") and isinstance(response.data, dict) else response
    if not isinstance(data, dict) or not data.get("ok"):
        return None

    slack_user = data.get("user")
    if not isinstance(slack_user, dict) or not slack_user.get("id"):
        return None
    return str(slack_user["id"])


def _escape_mrkdwn(text: str) -> str:
    """Neutralize Slack control syntax (`&`, `<`, `>`) so untrusted text can't inject mentions/links."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Matches a converter-emitted Slack angle token: `<dest>` or `<dest|label>`. Input `<`/`>`
# are escaped before conversion, so any literal angle bracket here was produced by the converter.
_SLACK_ANGLE_TOKEN_RE = re.compile(r"<([^<>|]*)(\|[^<>]*)?>")


def _defang_unsafe_slack_tokens(text: str) -> str:
    """Render any non-URL `<dest|label>` token the converter emitted as inert literal text.

    `markdown_to_mrkdwn` turns `[text](dest)` into Slack's `<dest|label>` form without checking
    the scheme, so untrusted signal content could smuggle a broadcast or ping via `[x](!channel)`
    or `[x](@U123)`. Tokens whose destination isn't a plain http(s) URL get their angle brackets
    escaped so Slack shows the text instead of firing a mention.
    """

    def _replace(match: re.Match[str]) -> str:
        if _is_safe_http_url(match.group(1)):
            return match.group(0)
        return match.group(0).replace("<", "&lt;").replace(">", "&gt;")

    return _SLACK_ANGLE_TOKEN_RE.sub(_replace, text)


def _markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert signal markdown to Slack mrkdwn, then neutralize any injected mentions.

    Escaping runs first so raw `<@U…>`/`<!channel>` in untrusted content can't reach Slack;
    after conversion, `_defang_unsafe_slack_tokens` strips any mention/broadcast the converter
    synthesized from a `[text](!channel)`-style link. Kept local rather than shared with the
    other `SlackMarkdownConverter` call sites: they render trusted LLM output, signals does not.
    """
    return _defang_unsafe_slack_tokens(_SLACK_MRKDWN_CONVERTER.convert(_escape_mrkdwn(text)))


def _resolve_reviewer_mentions(slack: SlackIntegration, reviewer_users: list[User]) -> list[str]:
    # `<@U…>` mention when the reviewer's email resolves in this workspace, else escaped name.
    mentions: list[str] = []
    for user in reviewer_users[:_MAX_REVIEWER_MENTIONS]:
        slack_user_id = lookup_slack_user_id_by_email(slack, user.email) if user.email else None
        mentions.append(f"<@{slack_user_id}>" if slack_user_id else _escape_mrkdwn(_posthog_user_display_name(user)))
    return mentions


def _format_source_product_labels(source_products: list[str]) -> str:
    if not source_products:
        return ""
    labels = [_SOURCE_PRODUCT_LABELS.get(product, product.replace("_", " ").title()) for product in source_products]
    return ", ".join(labels)


def _summary_excerpt(summary: str) -> str:
    """First line of the report description only, capped at 600 characters."""
    text = summary.strip()
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    if not first_line:
        return ""
    if len(first_line) <= _SUMMARY_EXCERPT_MAX_LEN:
        return first_line
    return first_line[: _SUMMARY_EXCERPT_MAX_LEN - 3].rstrip() + "..."


def _build_message_blocks(
    report: SignalReport,
    *,
    priority: str | None,
    source_products: list[str],
    reviewer_mentions: list[str],
    repository: str | None = None,
    implementation_pr_url: str | None = None,
    dismiss_button_value: str | None = None,
) -> tuple[list[dict], str]:
    title_line = report.title or "New signals inbox item"
    header_text = (
        title_line if len(title_line) <= _SLACK_HEADER_MAX_LEN else title_line[: _SLACK_HEADER_MAX_LEN - 3] + "..."
    )

    meta_parts: list[str] = []
    if priority:
        meta_parts.append(_slack_priority_label(priority))
    sources_line = _format_source_product_labels(source_products)
    if sources_line:
        meta_parts.append(sources_line)
    if repository:
        # Escape LLM/user-derived strings before they enter mrkdwn so a crafted value can't
        # inject `<!here>` / `<@U…>` mentions. Reviewer mentions are added pre-escaped elsewhere.
        meta_parts.append(_escape_mrkdwn(repository))

    body_parts: list[str] = []
    if meta_parts:
        body_parts.append(f"*{' · '.join(meta_parts)}*")
    summary_text = _summary_excerpt(report.summary or "")
    if summary_text:
        body_parts.append(_escape_mrkdwn(summary_text))
    if not body_parts:
        body_parts.append(f"*{_escape_mrkdwn(title_line)}*")

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(body_parts)}},
    ]

    # Reviewer mentions sit in the context line — they still carry the `<@U…>` token so Slack pings them.
    context_parts: list[str] = []
    if report.signal_count:
        signal_label = "signal" if report.signal_count == 1 else "signals"
        context_parts.append(f"{report.signal_count} {signal_label}")
    if reviewer_mentions:
        context_parts.append(f"👤 Suggested reviewers: {' '.join(reviewer_mentions)}")
    if context_parts:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "  ·  ".join(context_parts)}],
            }
        )

    action_elements: list[dict] = []
    if implementation_pr_url:
        action_elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Review PR", "emoji": True},
                "url": implementation_pr_url,
            }
        )
    action_elements.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Open in PostHog", "emoji": True},
            "url": f"{settings.SITE_URL}/project/{report.team_id}/inbox/reports/{report.id}",
        }
    )
    if dismiss_button_value:
        action_elements.append(
            {
                "type": "button",
                "action_id": SIGNALS_DISMISS_REPORT_ACTION_ID,
                "text": {"type": "plain_text", "text": "Dismiss", "emoji": True},
                "value": dismiss_button_value,
                "confirm": {
                    "title": {"type": "plain_text", "text": "Dismiss this report?"},
                    "text": {
                        "type": "mrkdwn",
                        "text": "This will dismiss the report for everyone. You can still find it in PostHog.",
                    },
                    "confirm": {"type": "plain_text", "text": "Dismiss"},
                    "deny": {"type": "plain_text", "text": "Cancel"},
                },
            }
        )
    blocks.append({"type": "actions", "elements": action_elements})

    priority_suffix = f" ({priority})" if priority else ""
    fallback_text = f"Inbox item{priority_suffix}: {_escape_mrkdwn(title_line)}"
    return blocks, fallback_text


# Bound how many evidence signals we post into a thread so a large report can't flood a channel.
_MAX_THREAD_SIGNALS = 30
# Slack section text caps at 3000 chars; leave headroom for the ellipsis.
_SIGNAL_CONTENT_MAX_LEN = 2900

# Explicit "Product · Signal type" labels, mirroring `signalCardSourceLine` in the canonical Inbox UI
# (PostHog Code's apps/code/.../detail/SignalCard.tsx). Keep in sync with it.
_SIGNAL_SOURCE_LINES: dict[tuple[str, str], str] = {
    ("error_tracking", "issue_created"): "Error tracking · New issue",
    ("error_tracking", "issue_reopened"): "Error tracking · Issue reopened",
    ("error_tracking", "issue_spiking"): "Error tracking · Volume spike",
    ("session_replay", "session_problem"): "Session replay · Session problem",
    ("session_replay", "session_segment_cluster"): "Session replay · Session segment cluster",
    ("session_replay", "session_analysis_cluster"): "Session replay · Session analysis cluster",
    ("llm_analytics", "evaluation"): "AI observability · Evaluation",
    ("llm_analytics", "evaluation_report"): "AI observability · Evaluation report",
    ("zendesk", "ticket"): "Zendesk · Ticket",
    ("github", "issue"): "GitHub · Issue",
    ("linear", "issue"): "Linear · Issue",
    ("pganalyze", "issue"): "pganalyze · Issue",
}


def _prettify_scout_name(skill_name: str) -> str:
    """Turn a scout's skill_name (e.g. "signals-scout-error-tracking") into a label (e.g. "Error tracking")."""
    cleaned = skill_name.removeprefix("signals-scout-").replace("-", " ").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def _signal_source_line(source_product: str, source_type: str, extra: dict | None = None) -> str:
    """Human-readable "Product · Signal type" line, mirroring `signalCardSourceLine` in the canonical Inbox UI."""
    explicit = _SIGNAL_SOURCE_LINES.get((source_product, source_type))
    if explicit is not None:
        return explicit
    if source_product == "error_tracking":
        type_label = source_type.replace("_", " ")
        return f"Error tracking · {type_label}" if type_label else "Error tracking"
    if source_product == "signals_scout" and source_type == "cross_source_issue":
        skill_name = extra.get("skill_name") if isinstance(extra, dict) else None
        pretty = _prettify_scout_name(skill_name) if isinstance(skill_name, str) else ""
        return f"Scout · {pretty}" if pretty else "Scout · Cross-source issue"
    product_label = source_product.replace("_", " ")
    type_label = source_type.replace("_", " ")
    return f"{product_label} · {type_label}" if type_label else product_label


def _is_safe_http_url(value: object) -> bool:
    # mrkdwn link injection guard: only plain http(s) URLs without the chars that break `<url|text>`.
    if not isinstance(value, str):
        return False
    if not (value.startswith("http://") or value.startswith("https://")):
        return False
    return not any(char in value for char in ("<", ">", "|"))


def _signal_detail_parts(source_product: str, extra: dict) -> list[str]:
    """A compact, source-specific metadata line mirroring the inbox SignalCard footer."""
    parts: list[str] = []
    if source_product == "github":
        number = extra.get("number")
        if number is not None:
            parts.append(f"#{_escape_mrkdwn(str(number))}")
        labels = extra.get("labels")
        if isinstance(labels, list) and labels:
            parts.append(", ".join(_escape_mrkdwn(str(label)) for label in labels[:5]))
        if _is_safe_http_url(extra.get("html_url")):
            parts.append(f"<{extra['html_url']}|View on GitHub>")
    elif source_product == "zendesk":
        if extra.get("priority"):
            parts.append(f"Priority: {_escape_mrkdwn(str(extra['priority']))}")
        if extra.get("status"):
            parts.append(f"Status: {_escape_mrkdwn(str(extra['status']))}")
        if _is_safe_http_url(extra.get("url")):
            parts.append(f"<{extra['url']}|Open ticket>")
    elif source_product == "llm_analytics":
        if extra.get("model"):
            parts.append(f"Model: {_escape_mrkdwn(str(extra['model']))}")
        if extra.get("provider"):
            parts.append(f"Provider: {_escape_mrkdwn(str(extra['provider']))}")
        trace_id = extra.get("trace_id")
        if trace_id:
            parts.append(f"Trace: `{_escape_mrkdwn(str(trace_id)[:12])}…`")
    elif source_product == "session_replay":
        if extra.get("problem_type"):
            parts.append(f"Problem: {_escape_mrkdwn(str(extra['problem_type']).replace('_', ' '))}")
    return parts


def _build_signal_thread_blocks(signal: dict) -> tuple[list[dict], str]:
    """Render one evidence signal as Slack blocks, mirroring an inbox SignalCard."""
    source_product = str(signal.get("source_product") or "")
    source_type = str(signal.get("source_type") or "")
    raw_extra = signal.get("extra")
    extra = raw_extra if isinstance(raw_extra, dict) else {}

    source_line = _escape_mrkdwn(_signal_source_line(source_product, source_type, extra))
    header_line = f"*{source_line}*"
    blocks: list[dict] = [{"type": "context", "elements": [{"type": "mrkdwn", "text": header_line}]}]

    content = (signal.get("content") or "").strip()
    if content:
        # Render markdown to mrkdwn first, then truncate the rendered output: truncating raw
        # markdown could slice a link/emphasis token mid-syntax, and conversion can lengthen
        # text past Slack's section limit. Truncating post-defang output stays safe — a
        # trailing cut can't synthesize a live mention (no closing `>` can appear).
        rendered = _markdown_to_slack_mrkdwn(content)
        if len(rendered) > _SIGNAL_CONTENT_MAX_LEN:
            rendered = rendered[: _SIGNAL_CONTENT_MAX_LEN - 1].rstrip() + "…"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": rendered}})

    detail_parts = _signal_detail_parts(source_product, extra)
    if detail_parts:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "  ·  ".join(detail_parts)}]})

    # Slack parses mrkdwn mentions in `text` (push notifications, search) even with blocks present, so both
    # the source line (escaped above) and content are escaped here too.
    fallback = source_line if not content else f"{source_line}: {_escape_mrkdwn(content[:120])}"
    return blocks, fallback


def _post_signal_evidence_thread(
    slack: SlackIntegration,
    channel_id: str,
    thread_ts: str,
    signals: list[dict],
) -> None:
    """Post each evidence signal as a reply in the notification's Slack thread. Best-effort."""
    for signal in signals[:_MAX_THREAD_SIGNALS]:
        blocks, text = _build_signal_thread_blocks(signal)
        try:
            slack.client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, blocks=blocks, text=text)
        except Exception:
            logger.exception("Failed to post signal evidence to inbox notification thread")

    # The overflow note reflects signals intentionally withheld by the cap — not transient post failures.
    overflow = max(0, len(signals) - _MAX_THREAD_SIGNALS)
    if overflow > 0:
        try:
            slack.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"+{overflow} more {'signal' if overflow == 1 else 'signals'} in PostHog",
            )
        except Exception:
            logger.exception("Failed to post signal evidence overflow note to inbox notification thread")


class _ChannelRoute:
    """One Slack channel and the reviewers routed to it (mentioned only there)."""

    def __init__(self, integration: Integration, channel: str, *, is_team_channel: bool) -> None:
        self.integration = integration
        self.channel = channel
        self.is_team_channel = is_team_channel
        self.users: list[User] = []


def _build_reviewer_routes(
    report: SignalReport,
    *,
    priority: str | None,
    team_integration: Integration | None,
    team_channel: str | None,
) -> list[_ChannelRoute]:
    """Route resolvable suggested reviewers to a destination channel, mentioning them there.

    Own channel (filtered by the reviewer's min-priority) if set, else the team default. A reviewer
    filtered out of their own channel does not fall back to the team channel — that was their choice.
    Reviewers sharing a destination are grouped so each channel is posted to once, mentioning only
    its own reviewers. When no suggested reviewer resolves, the report is still delivered to the
    team-default channel (if configured) with no mentions, so a team is notified even when none of
    its members are linked to a resolvable GitHub identity.
    """
    reviewer_user_ids = _resolve_suggested_reviewer_user_ids(report)
    reviewer_users = {user.id: user for user in User.objects.filter(id__in=reviewer_user_ids)}
    own_configs = _own_channel_configs_by_user(report.team_id, reviewer_user_ids)

    # Keyed by (integration_id, channel_id) so a reviewer's own channel and the team
    # default collapse into one post when they resolve to the same Slack channel.
    routes: dict[tuple[int, str], _ChannelRoute] = {}

    def _route_for(integration: Integration, channel: str, *, is_team_channel: bool) -> _ChannelRoute:
        key = (integration.id, _channel_id_from_target(channel))
        route = routes.get(key)
        if route is None:
            route = _ChannelRoute(integration, channel, is_team_channel=is_team_channel)
            routes[key] = route
        return route

    for user_id in sorted(reviewer_user_ids):
        user = reviewer_users.get(user_id)
        if user is None:
            continue

        config = own_configs.get(user_id)
        if config is not None:
            if not _meets_min_priority(priority, config.slack_notification_min_priority):
                continue
            integration = config.slack_notification_integration
            channel = config.slack_notification_channel
            is_team_channel = False
        elif team_integration is not None and team_channel:
            integration = team_integration
            channel = team_channel
            is_team_channel = True
        else:
            continue

        if integration is None or not channel:
            continue
        _route_for(integration, channel, is_team_channel=is_team_channel).users.append(user)

    # No suggested reviewer resolved to a PostHog user: deliver to the team-default channel (if
    # configured) so the team is still notified, without @-mentions — the message omits the
    # suggested-reviewers section when there is nobody to tag. Per-user own channels are reviewer
    # notifications, so they are not used here.
    if not reviewer_user_ids and team_integration is not None and team_channel:
        _route_for(team_integration, team_channel, is_team_channel=True)

    return list(routes.values())


def dispatch_inbox_item_notifications(
    report_id: str,
    team_id: int,
    source_products: list[str] | None = None,
    signals: list[dict] | None = None,
) -> int:
    """Send Slack notifications for a newly-ready report.

    Returns the number of top-level notification messages sent (one per destination
    channel); threaded evidence replies are not included in the count.

    When ``signals`` is provided, each evidence signal is posted as a reply in the
    notification's thread, mirroring the inbox UI so reviewers can scan it from Slack.

    Best-effort: per-destination Slack errors are logged, not raised.
    """
    try:
        report = SignalReport.objects.get(id=report_id, team_id=team_id)
    except SignalReport.DoesNotExist:
        logger.warning(
            "dispatch_inbox_item_notifications: report not found",
            extra={"report_id": report_id, "team_id": team_id},
        )
        return 0

    # Mirror the inbox Reports tab: notify only for actionable reports (READY is enforced upstream
    # in the notification activity). Priority is read below for the message label and min-priority
    # routing, but it's optional now — an actionable report notifies even without a priority.
    if _latest_actionability(report) not in _ACTIONABLE_VALUES:
        logger.info(
            "dispatch_inbox_item_notifications: report not actionable, skipping",
            extra={"report_id": report_id, "team_id": team_id},
        )
        return 0

    priority = _latest_priority(report)
    team_integration = _get_team_slack_integration(team_id)
    team_channel = _team_notification_channel(team_id) if team_integration is not None else None

    routes = _build_reviewer_routes(
        report,
        priority=priority,
        team_integration=team_integration,
        team_channel=team_channel,
    )
    if not routes:
        # No channel to deliver to: no reviewer resolved to a destination and no notification channel
        # is configured for the team (no per-user own channel and no team default). Log the inputs so
        # it's diagnosable.
        logger.info(
            "dispatch_inbox_item_notifications: no notification channel configured, skipping",
            extra={
                "report_id": report_id,
                "team_id": team_id,
                "priority": priority,
                "has_team_integration": team_integration is not None,
                "has_team_channel": team_channel is not None,
            },
        )
        return 0

    sources = source_products or []
    repository = _report_repository(report)
    implementation_pr_url = fetch_implementation_pr_urls_for_reports([str(report.id)]).get(str(report.id))

    sent = 0
    for route in routes:
        channel_id = _channel_id_from_target(route.channel)
        log_context = {
            "report_id": report_id,
            "team_id": team_id,
            "channel": _channel_display_name(route.channel),
            "destination": "team" if route.is_team_channel else "user",
        }
        try:
            slack = SlackIntegration(route.integration)
            mentions = _resolve_reviewer_mentions(slack, route.users)
            dismiss_button_value = json.dumps(
                {
                    "integration_id": route.integration.id,
                    "report_id": str(report.id),
                    "team_id": team_id,
                }
            )
            blocks, text = _build_message_blocks(
                report,
                priority=priority,
                source_products=sources,
                reviewer_mentions=mentions,
                repository=repository,
                implementation_pr_url=implementation_pr_url,
                dismiss_button_value=dismiss_button_value,
            )
            response = slack.client.chat_postMessage(channel=channel_id, blocks=blocks, text=text)
            sent += 1
            thread_ts = response.get("ts") if hasattr(response, "get") else None
            if signals and thread_ts:
                _post_signal_evidence_thread(slack, channel_id, str(thread_ts), signals)
        except Exception:
            logger.exception("Failed to deliver signals inbox-item Slack notification", extra=log_context)
    logger.info(
        "dispatch_inbox_item_notifications: complete",
        extra={"report_id": report_id, "team_id": team_id, "messages_sent": sent, "routes": len(routes)},
    )
    return sent
