import re
import json
import hashlib
from typing import Any

from structlog import get_logger

from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig, redacted_record

logger = get_logger(__name__)

GITHUB_SUMMARIZATION_PROMPT = """Summarize this GitHub issue for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) that captures the core issue
2. A concise summary capturing the problem or request, the product area affected, and key context like error messages or what the user was doing when the issue occurred

Strip raw logs, full stack traces, and large code blocks — but keep specific error messages and high-level reproduction context if they clarify the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<issue>
{description}
</issue>
"""

GITHUB_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a GitHub issue, determine if it contains actionable product feedback.

An issue is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem or regression
- A self-hosted deployment or configuration problem
- A question about how to use the product
- A gap or error in documentation that caused confusion
- and similar cases

An issue is NOT_ACTIONABLE if it is:
- A bot-generated issue (dependency bumps, stale-bot closures, CI notifications, release automation)
- Spam, abuse, or profanity with no real feedback
- A meta/tracking issue with no substantive feedback — issues that contain only a title and a bare link or a short reminder without describing a problem, use case, or solution (release checklists, sprint trackers, experiment-to-do notes)
- A duplicate that only says "same as #X" with no new information

The issue may end with a record_metadata block naming its author. `author_login` is the GitHub handle that filed it, and `author_association` is that account's relationship to the repository: OWNER, MEMBER, and COLLABORATOR are maintainers, while CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR, and NONE are reporters from outside the org. A handle ending in [bot] is automation, so treat what it files as bot-generated. Beyond that, the author is context and not a verdict — a bug report from an outside reporter is exactly the feedback worth capturing, so never classify an issue as NOT_ACTIONABLE just because its author isn't a maintainer.

When in doubt, classify as ACTIONABLE. GitHub issues are filed intentionally, so err on the side of capturing the signal. However, if an issue clearly matches one of the NOT_ACTIONABLE categories above, classify it as NOT_ACTIONABLE regardless.

<issue>
{description}
</issue>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

REQUIRED_FIELDS = ("id", "title", "body")

PASSTHROUGH_FIELDS = ("html_url", "number", "labels", "created_at", "updated_at", "locked", "state")
# TODO: Add "comments", but they can be pretty heavy, so better to iterate on them later,
# either when adding weight-defining logic, or when we decide to include them into the description

# Columns behind the author identity on `extra`. `author_association` lands verbatim; `author_login`
# is lifted out of the nested `user` object, which otherwise carries a pile of avatar and API URLs
# that triage has no use for.
AUTHOR_FIELDS = ("author_association", "user")

# `user` never belongs in a log line: the emitter keeps the handle and drops the numeric id and the
# avatar and API URLs, and the shared pipeline logs whole records when an emitter raises.
UNLOGGABLE_FIELDS = ("user",)

EXTRA_FIELDS = (*PASSTHROUGH_FIELDS, "author_login", "author_association", "depends_on_issues")

MAX_DEPENDS_ON_ISSUES = 10

# A dependency line starts a line or a list item, so a sentence that only mentions an issue in
# passing is not one. Bold markers and a trailing colon are allowed around the phrase.
_DEPENDENCY_LINE_RE = re.compile(
    r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?(?:\*\*|__)?(?:depends\s+on|blocked\s+by)(?:\*\*|__)?\s*:?(?:\*\*|__)?\s+(?P<refs>.+)$",
    re.IGNORECASE,
)
_ISSUE_REF_RE = re.compile(
    r"https?://(?:www\.)?github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/issues/(?P<url_number>\d+)(?:[/?#]\S*)?"
    r"|(?P<repo>[\w.-]+/[\w.-]+)?#(?P<number>\d+)\b",
    re.IGNORECASE,
)
# Commas, "and", and "&" join several refs on one line. Any other text ends the list, so an issue
# mentioned later in the same sentence is not read as a dependency.
_REF_SEPARATOR_RE = re.compile(r"\s*(?:,|&|\band\b)?\s*", re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _loggable(record: dict[str, Any]) -> dict[str, Any]:
    return redacted_record(record, UNLOGGABLE_FIELDS)


def github_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
        title = record["title"]
        body = record["body"]
    except KeyError as e:
        msg = f"GitHub issue record missing required field {e}"
        logger.exception(msg, record=_loggable(record), team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id or not title:
        msg = f"GitHub issue record has empty required field: id={issue_id!r}, title={title!r}"
        logger.exception(msg, record=_loggable(record), team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg)
    body = body or ""
    extra = _build_extra(record)
    labels = sorted(extra["labels"])
    material_version = hashlib.sha256(
        json.dumps(
            {
                "title": title,
                "body": body,
                "labels": labels,
                "state": extra.get("state"),
                "locked": extra.get("locked"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    metadata = [f"State: {extra.get('state') or 'unknown'}"]
    if labels:
        metadata.append(f"Labels: {', '.join(labels)}")
    return SignalEmitterOutput(
        source_product="github",
        source_type="issue",
        source_id=str(issue_id),
        description=f"{title}\n{body}\n\n" + "\n".join(metadata),
        weight=1.0,
        extra=extra,
        idempotency_key=f"{issue_id}:{material_version}",
        existing_source_only=not body or extra.get("state") == "closed",
    )


def _author_login(raw_user: Any) -> str | None:
    """Lift `login` out of a GitHub user object, which the warehouse stores as a JSON string.

    Unlike labels, a user object we can't read degrades to an unknown author rather than raising:
    the author is context for triage, not something the signal is meaningless without.
    """
    if isinstance(raw_user, str):
        try:
            raw_user = json.loads(raw_user)
        except (json.JSONDecodeError, TypeError):
            # The blob itself names a person, so log only enough to spot a shape change upstream.
            logger.warning(
                "Ignoring unparseable GitHub issue user field",
                signals_type="data-import-signals",
                raw_user_length=len(raw_user),
            )
            return None
    if not isinstance(raw_user, dict):
        return None
    login = raw_user.get("login")
    return login if isinstance(login, str) and login else None


def _build_extra(record: dict[str, Any]) -> dict[str, Any]:
    extra = {k: v for k, v in record.items() if k in PASSTHROUGH_FIELDS}
    # Always present, so the contract shape doesn't shift when a repo or a sync withholds the author.
    extra["author_login"] = _author_login(record.get("user"))
    extra["author_association"] = record.get("author_association") or None
    extra["depends_on_issues"] = parse_depends_on_issues(record.get("body") or "", extra.get("html_url"))
    raw_labels = extra.get("labels")
    if raw_labels is None:
        extra["labels"] = []
    elif isinstance(raw_labels, str):
        try:
            parsed = json.loads(raw_labels)
        except (json.JSONDecodeError, TypeError) as e:
            msg = f"GitHub issue labels field is not valid JSON: {raw_labels!r}"
            logger.exception(msg, record=_loggable(record), signals_type="data-import-signals")
            raise ValueError(msg) from e
        if not isinstance(parsed, list):
            msg = f"GitHub issue labels field is not a JSON array: {raw_labels!r}"
            logger.exception(msg, record=_loggable(record), signals_type="data-import-signals")
            raise ValueError(msg)
        extra["labels"] = [label["name"] for label in parsed if isinstance(label, dict) and "name" in label]
    else:
        msg = f"GitHub issue labels field has unexpected type {type(raw_labels).__name__}: {raw_labels!r}"
        logger.exception(msg, record=_loggable(record), signals_type="data-import-signals")
        raise ValueError(msg)
    return extra


def parse_depends_on_issues(body: str, html_url: Any) -> list[dict[str, Any]]:
    """The issues that `body` names on "Depends on" or "Blocked by" lines, as `{repository, number}`.

    Code blocks, quotes, and inline code are skipped, because they quote other text rather than
    state this issue's dependencies. A `#123` ref takes the repository of the issue itself, so it is
    dropped when `html_url` does not parse. References to the issue itself are dropped.
    """
    own = GitHubIntegrationBase.parse_issue_url(html_url) if isinstance(html_url, str) else None
    own_repository = f"{own.owner}/{own.repo}".lower() if own else None
    refs: list[dict[str, Any]] = []
    in_fence = False
    for line in body.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith(">"):
            continue
        match = _DEPENDENCY_LINE_RE.match(_INLINE_CODE_RE.sub("", line))
        if match is None:
            continue
        for repository, number in _leading_refs(match.group("refs"), own_repository):
            ref = {"repository": repository, "number": number}
            if (repository == own_repository and own is not None and number == own.number) or ref in refs:
                continue
            refs.append(ref)
            if len(refs) >= MAX_DEPENDS_ON_ISSUES:
                return refs
    return refs


def _leading_refs(text: str, own_repository: str | None) -> list[tuple[str, int]]:
    refs: list[tuple[str, int]] = []
    position = 0
    while True:
        separator = _REF_SEPARATOR_RE.match(text, position)
        match = _ISSUE_REF_RE.match(text, separator.end() if separator else position)
        if match is None:
            return refs
        repository = match.group("url_repo") or match.group("repo") or own_repository
        number = match.group("url_number") or match.group("number")
        if repository:
            refs.append((repository.lower(), int(number)))
        position = match.end()


GITHUB_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="github",
    source_type="issue",
    emitter=github_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    sync_with_source=True,
    partition_field="updated_at",
    partition_field_is_datetime_string=True,
    fields=REQUIRED_FIELDS + PASSTHROUGH_FIELDS + AUTHOR_FIELDS,
    max_records=1000,
    first_sync_lookback_days=1,  # 24 hours
    actionability_prompt=GITHUB_ACTIONABILITY_PROMPT,
    actionability_context_fields=("author_login", "author_association"),
    unloggable_fields=UNLOGGABLE_FIELDS,
    summarization_prompt=GITHUB_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
