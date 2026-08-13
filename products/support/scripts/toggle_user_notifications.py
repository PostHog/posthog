#!/usr/bin/env python3
"""Toggle a PostHog email notification setting for a list of users, given their email addresses.

Notification preferences live only on the individual user (`User.partial_notification_settings`),
so there is no organization-wide switch and no admin UI for changing them on someone's behalf.
This script is the staff-side equivalent: it resolves each email to a user UUID and PATCHes that
one setting, one request per user.

Discovery uses `GET /api/users/?email=<email>`, which only returns other users' rows for a staff
credential (`UserViewSet.get_queryset` filters everyone else down to themselves). Mutation is
`PATCH /api/users/<uuid>/`, whose `notification_settings` validator merges the payload over the
user's existing settings - top level for scalars, one level deep for the per-project/per-org maps -
so a partial body never clobbers unrelated preferences.

Requires a **staff, non-impersonating** credential, and checks all three preconditions up front
because they surface as indistinguishable 403s at PATCH time:

- Non-staff credentials get HTTP 403 on any UUID other than `@me`.
- Impersonated sessions are blocked even for their own user: `/api/users/` is in
  `IMPERSONATION_BLOCKED_PATHS`, so every non-idempotent request during impersonation is rejected
  with `impersonation_path_blocked`. Log out of impersonation and use your own staff session or key.
- With `--session-id`, the session must be inside its sensitive-action window. Writing notification
  settings isn't in `time_sensitive_allow_if_only_fields`, so `TimeSensitiveActionPermission`
  requires a session younger than `SESSION_SENSITIVE_ACTIONS_AGE` (2h) and otherwise 403s with
  `sensitive_action_required_reauth` - the re-auth modal the UI shows. Prefer
  `--personal-api-key`: the permission returns early for non-session auth, so keys never hit this.
  Re-authenticating rotates the session key (`session.cycle_key()`), deliberately invalidating a
  cookie copied beforehand, so a re-auth means copying the new `sessionid`.

Writing to someone's account while they aren't present is a support action, not a routine one -
have the user's explicit request on record first. Every write therefore needs --reason, which is
echoed in the plan, the confirmation prompt, and the closing summary, and stored in the --output
JSON alongside the acting staff email and a UTC timestamp so a run can be attached to the ticket
that motivated it.

That record is local to this run, not a server-side audit trail, and the distinction matters:
`partial_notification_settings` sits in `field_exclusions` for the User activity-log scope, so
`changes_between` yields no changes and `log_activity` drops the "updated" entry entirely. The
`user updated` analytics event that does fire is attributed to the target user's distinct_id with
no reference to the operator. Nothing server-side records that staff made this change on someone
else's behalf, so --reason plus --output is the only durable evidence - write it for the next
person reading the ticket, and keep the file.

Polarity differs between settings and is the main footgun here: `all_weekly_digest_disabled=True`
means the digest is OFF, while `error_tracking_weekly_digest=True` means it is ON. --enable and
--disable are always expressed as "does this user receive the notification", and the script writes
whichever raw boolean that implies. Use --list-settings to see every setting, its polarity, and its
default, and --dry-run to see the exact JSON body before anything is written.

Not every setting is a toggle. Number settings (currently `data_pipeline_error_threshold`) take
--value instead of --enable/--disable, and fall back to PostHog's own default when --value is
omitted, which is the usual way to undo a previous change. The value is range-checked before any
request runs, and the resolved number is echoed in the plan so a defaulted run is never ambiguous.

Note: unlike the other scripts here, there is no --project-id - users are not project-scoped, and
POSTHOG_PROJECT_ID is ignored. Some settings are scoped to a project or organization; those take
--scope instead.

Usage:
  export POSTHOG_PERSONAL_API_KEY=phx_...   # staff key, needs user:read and user:write
  python products/support/scripts/toggle_user_notifications.py --list-settings
  python products/support/scripts/toggle_user_notifications.py \\
      a@example.com b@example.com --setting all_weekly_digest_disabled --disable --dry-run
  python products/support/scripts/toggle_user_notifications.py \\
      --emails-file ./users.txt --setting project_weekly_digest_disabled --scope 4711 --disable \\
      --reason "customer asked to mute this project's digest, ZD-12345" --output ./run.json
  python products/support/scripts/toggle_user_notifications.py \\
      --emails-file ./users.txt --setting data_pipeline_error_threshold --value 0.25 --dry-run

--host accepts a full instance URL or the PostHog Cloud region shorthands us/eu.

When a personal API key can't be created, pass a browser session instead: --session-id (env
POSTHOG_SESSION_ID) with the value of the `sessionid` cookie from devtools. It must be your own
staff session - an impersonated one cannot write to /api/users/ at all.
"""

import os
import re
import sys
import json
import argparse
import datetime
from collections import Counter
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from lib.console import confirm, format_status_counts, log, printable
from lib.errors import PostHogScriptError
from lib.posthog_api import request_with_retries, resolve_host, setup_session_auth

# Scope kinds. A setting with scope=None stores a plain boolean; the others store a map keyed by
# the scope value, so --scope identifies which entry to write.
SCOPE_TEAM = "team"
SCOPE_ORGANIZATION = "organization"
SCOPE_PIPELINE = "pipeline"
SCOPE_TYPE_TEAM = "type_team"

# Mirrors _PIPELINE_ID_PATTERN in posthog/api/user.py - the API rejects anything else.
PIPELINE_ID_PATTERN = re.compile(r"^(?:hog_function|batch_export|plugin_config):[0-9a-zA-Z-]{1,128}$")

# NotificationType values from products/notifications/backend/facade/enums.py, the only accepted
# keys for realtime_notifications_disabled.
REALTIME_NOTIFICATION_TYPES = (
    "comment_mention",
    "alert_firing",
    "issue_assigned",
    "approval_requested",
    "approval_resolved",
    "experiment_concluded",
    "pipeline_failure",
    "project_created",
    "usage_spike",
    "reminder",
    "web_analytics_digest",
    "achievement_unlocked",
    "subscription_nudge",
    "email_reputation",
    "materialization_failure",
)

# Writing any explicit value to these clears the "not configured" state that triggers one-shot
# auto-selection of the user's busiest project on their first digest (auto_select_digest_project in
# posthog/tasks/email_utils.py). Enabling one project therefore also opts the user out of ever being
# auto-enrolled elsewhere.
AUTO_SELECT_KEYS = frozenset(
    {
        "error_tracking_weekly_digest_project_enabled",
        "web_analytics_weekly_digest_project_enabled",
    }
)

MIN_REASON_LENGTH = 10

# Warn rather than refuse this close to the window closing - a short list may still finish.
SENSITIVE_WINDOW_WARN_SECONDS = 300


# Setting kinds. Booleans are driven by --enable/--disable; numbers take a --value (or fall back
# to the PostHog default), because "on/off" says nothing useful about a threshold.
KIND_BOOLEAN = "boolean"
KIND_NUMBER = "number"


# Plain stdlib dataclass rather than posthog.dataclasses.frozen: these scripts run standalone
# (python products/support/scripts/<name>.py) and must not import the Django app.
@dataclass(frozen=True, kw_only=True, slots=True)
class NotificationSetting:
    """One entry of the Notifications TypedDict in posthog/models/user.py."""

    key: str
    default: Any
    scope: Optional[str]
    summary: str
    kind: str = KIND_BOOLEAN
    receives_when_true: Optional[bool] = None
    """Boolean settings only. True when storing `True` means the user receives the notification;
    False for the `*_disabled` settings, where `True` means suppressed."""
    bounds: Optional[tuple[float, float]] = None
    """Number settings only: the inclusive range the API accepts."""

    def __post_init__(self) -> None:
        # Registry authoring guard - a kind/field mismatch here would otherwise surface as a
        # confusing runtime failure or, worse, a silently wrong value written to an account.
        if self.kind == KIND_BOOLEAN and self.receives_when_true is None:
            raise PostHogScriptError(f"{self.key}: boolean settings must declare receives_when_true")
        if self.kind == KIND_NUMBER and self.bounds is None:
            raise PostHogScriptError(f"{self.key}: number settings must declare bounds")

    def raw_value_for(self, *, receives: bool) -> bool:
        """Translate the operator's intent ("should they receive it?") into the stored boolean."""
        if self.receives_when_true is None:
            raise PostHogScriptError(f"{self.key} is not a boolean setting")
        return receives if self.receives_when_true else not receives

    def describe_default(self) -> str:
        if self.kind == KIND_NUMBER:
            low, high = self.bounds or (0.0, 1.0)
            return f"{json.dumps(self.default)} (accepts {low}-{high})"
        if self.scope is not None:
            return "not configured"
        receives = self.default if self.receives_when_true else not self.default
        return f"{'on' if receives else 'off'} (stores {json.dumps(self.default)})"


SETTINGS: tuple[NotificationSetting, ...] = (
    NotificationSetting(
        key="all_weekly_digest_disabled",
        receives_when_true=False,
        default=False,
        scope=None,
        summary="Weekly product digest, across every project. Master switch for the digest family.",
    ),
    NotificationSetting(
        key="project_weekly_digest_disabled",
        receives_when_true=False,
        default={},
        scope=SCOPE_TEAM,
        summary="Weekly product digest for one project. --scope is the numeric project (team) ID.",
    ),
    NotificationSetting(
        key="error_tracking_weekly_digest",
        receives_when_true=True,
        default=True,
        scope=None,
        summary="Weekly error tracking digest (Mondays). Also gated per project by the setting below.",
    ),
    NotificationSetting(
        key="error_tracking_weekly_digest_project_enabled",
        receives_when_true=True,
        default={},
        scope=SCOPE_TEAM,
        summary="Error tracking digest for one project. --scope is the numeric project (team) ID.",
    ),
    NotificationSetting(
        key="web_analytics_weekly_digest",
        receives_when_true=True,
        default=True,
        scope=None,
        summary="Weekly web analytics digest. Additionally gated by a feature flag server-side.",
    ),
    NotificationSetting(
        key="web_analytics_weekly_digest_project_enabled",
        receives_when_true=True,
        default={},
        scope=SCOPE_TEAM,
        summary="Web analytics digest for one project. --scope is the numeric project (team) ID.",
    ),
    NotificationSetting(
        key="error_tracking_issue_assigned",
        receives_when_true=True,
        default=True,
        scope=None,
        summary="An error tracking issue is assigned to the user (or to a role they belong to).",
    ),
    NotificationSetting(
        key="discussions_mentioned",
        receives_when_true=True,
        default=True,
        scope=None,
        summary="The user is @mentioned in a comment or discussion.",
    ),
    # The one key whose name lies about its polarity: it reads like the `*_disabled` suppression
    # keys but means "notify me when a pipeline breaks", so True sends
    # (should_send_notification -> `settings.get("plugin_disabled", True)`).
    #
    # It gates the family, not one email: get_members_to_notify_for_pipeline_error filters on it
    # first, then narrows by data_pipeline_error_threshold and pipeline_notifications_disabled.
    #
    # Scope is narrower than the model's own "plugins, hog functions, batch exports" comment
    # claims. Only legacy plugins (send_fatal_plugin_error) and batch exports
    # (send_batch_export_run_failure) have live callers; send_hog_function_disabled exists but its
    # caller is commented out in posthog/tasks/plugin_server.py, so modern destinations email
    # nothing through here today. Don't promise a customer this silences destination alerts.
    NotificationSetting(
        key="plugin_disabled",
        receives_when_true=True,
        default=True,
        scope=None,
        summary=(
            "Master switch for pipeline failure emails - a legacy plugin auto-disabled, or a batch "
            "export run failed. Positive despite the name: enabling it means notify. Narrowed by "
            "data_pipeline_error_threshold and pipeline_notifications_disabled. Does not currently "
            "cover hog function destinations."
        ),
    ),
    NotificationSetting(
        key="pipeline_notifications_disabled",
        receives_when_true=False,
        default={},
        scope=SCOPE_PIPELINE,
        summary=(
            "Pipeline failure emails for one pipeline. --scope is hog_function:<uuid>, "
            "batch_export:<uuid> or plugin_config:<id>."
        ),
    ),
    NotificationSetting(
        key="project_api_key_exposed",
        receives_when_true=True,
        default=True,
        scope=None,
        summary="A project secret/private API key was detected exposed. Only sent to org admins and owners.",
    ),
    NotificationSetting(
        key="materialized_view_sync_failed",
        receives_when_true=True,
        default=False,
        scope=None,
        summary="Master switch for materialized view sync failures. Off by default, so the two below are inert.",
    ),
    NotificationSetting(
        key="materialized_view_sync_failed_daily",
        receives_when_true=True,
        default=True,
        scope=None,
        summary="Deliver materialized view failures as one daily digest. Needs the master switch on.",
    ),
    NotificationSetting(
        key="materialized_view_sync_failed_immediate",
        receives_when_true=True,
        default=False,
        scope=None,
        summary="Deliver a materialized view failure the moment it starts failing. Needs the master switch on.",
    ),
    NotificationSetting(
        key="organization_member_join_email_disabled",
        receives_when_true=False,
        default={},
        scope=SCOPE_ORGANIZATION,
        summary="'Someone joined your organization' emails. --scope is the organization UUID.",
    ),
    NotificationSetting(
        key="task_comments_slack_dm",
        receives_when_true=True,
        default=False,
        scope=None,
        summary="Slack DM (not email) for task comment mentions, replies, and owned items.",
    ),
    NotificationSetting(
        key="realtime_notifications_disabled",
        receives_when_true=False,
        default={},
        scope=SCOPE_TYPE_TEAM,
        summary=(
            "In-app realtime notifications, not email. --scope is <notification_type>:<team_id>; "
            "see --list-settings for the valid types."
        ),
    ),
    NotificationSetting(
        key="data_pipeline_error_threshold",
        kind=KIND_NUMBER,
        default=0.01,
        bounds=(0.0, 1.0),
        scope=None,
        summary=(
            "Failure rate above which pipeline errors notify, as a fraction: 0.01 is 1%. "
            "Raise it to quiet a flaky destination; 0.0 notifies on any failure."
        ),
    ),
)

SETTINGS_BY_KEY = {setting.key: setting for setting in SETTINGS}


@dataclass(frozen=True, kw_only=True, slots=True)
class PlannedChange:
    """One user's before/after for the chosen setting."""

    email: str
    uuid: str
    current: Any
    desired: Any
    clears_auto_select: bool

    @property
    def is_noop(self) -> bool:
        # `current` is None when unset, which is never equal to the desired bool, so an
        # unconfigured setting is always written rather than assumed to match a default.
        return bool(self.current == self.desired)


def format_current(value: Any) -> str:
    return "not set" if value is None else json.dumps(value)


def list_settings() -> None:
    """Print every notification setting, its polarity or range, default, and scope."""
    log("Notification settings (from the Notifications TypedDict in posthog/models/user.py)")
    log("")
    log("--enable/--disable always mean 'does the user receive this notification'. The 'stores'")
    log("note shows the raw boolean written for --enable, which is inverted for *_disabled keys.")
    log("Number settings take --value instead, and fall back to the PostHog default when omitted.")
    log("")
    booleans = [s for s in SETTINGS if s.kind == KIND_BOOLEAN]
    unscoped = [s for s in booleans if s.scope is None]
    scoped = [s for s in booleans if s.scope is not None]
    numbers = [s for s in SETTINGS if s.kind == KIND_NUMBER]

    log(f"Plain toggles ({len(unscoped)}) - no --scope:")
    for setting in unscoped:
        log(f"  {setting.key}")
        log(
            f"      default: {setting.describe_default()}; --enable stores {json.dumps(setting.raw_value_for(receives=True))}"
        )
        log(f"      {setting.summary}")
    log("")
    log(f"Scoped toggles ({len(scoped)}) - require --scope:")
    for setting in scoped:
        log(f"  {setting.key}  (--scope = {setting.scope})")
        log(
            f"      default: {setting.describe_default()}; --enable stores {json.dumps(setting.raw_value_for(receives=True))}"
        )
        log(f"      {setting.summary}")
    log("")
    log(f"Number settings ({len(numbers)}) - take --value, not --enable/--disable:")
    for setting in numbers:
        log(f"  {setting.key}")
        log(f"      default: {setting.describe_default()}")
        log(f"      {setting.summary}")
    log("")
    log(f"Valid notification types for realtime_notifications_disabled: {', '.join(REALTIME_NOTIFICATION_TYPES)}")
    log("")
    log(
        "Settings whose absence is meaningful: "
        + ", ".join(sorted(AUTO_SELECT_KEYS))
        + ". While unset, the first digest auto-enrolls the user's busiest project; writing any "
        "explicit value ends that."
    )


def read_emails(positional: list[str], emails_file: Optional[str]) -> list[str]:
    """Collect emails from positional args and/or a file, de-duplicated case-insensitively.

    File format is one email per line; blank lines and `#` comments are skipped.
    """
    collected = list(positional)
    if emails_file:
        try:
            with open(emails_file) as handle:
                for line in handle:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        collected.append(stripped)
        except OSError as err:
            raise PostHogScriptError(f"Could not read --emails-file {emails_file}: {err}") from err

    seen: set[str] = set()
    emails: list[str] = []
    for email in collected:
        lowered = email.lower()
        if lowered not in seen:
            seen.add(lowered)
            emails.append(email)
    return emails


def verify_staff_credential(session: requests.Session, host: str, *, session_auth: bool) -> str:
    """Fail fast unless the credential is staff, not impersonating, and able to act.

    All three restrictions live in front of /api/users/ and surface as indistinguishable 403s, so
    check them once here rather than letting every PATCH fail with an opaque body.
    """
    response = request_with_retries(session, "GET", f"{host}/api/users/@me/")
    if response.status_code != 200:
        raise PostHogScriptError(
            f"Could not identify the authenticated user (HTTP {response.status_code}): {printable(response.text[:300])}"
        )
    me = response.json()
    if me.get("is_impersonated"):
        raise PostHogScriptError(
            "This is an impersonated session. /api/users/ is in IMPERSONATION_BLOCKED_PATHS, so no "
            "notification setting can be written while impersonating - not even for the impersonated "
            "user. Log out of impersonation and rerun with your own staff session or personal API key."
        )
    if not me.get("is_staff"):
        raise PostHogScriptError(
            f"{printable(str(me.get('email')))} is not a staff user, so it can only read and write its "
            "own settings (/api/users/@me/). Editing other users needs a staff credential."
        )
    email = str(me.get("email") or "unknown")
    if session_auth:
        check_sensitive_window(me, email)
    log(f"Authenticated as staff user {printable(email)}")
    return email


def check_sensitive_window(me: dict[str, Any], email: str) -> None:
    """Refuse a session whose sensitive-action window has closed, before any PATCH goes out.

    Writing notification settings is a sensitive action, so TimeSensitiveActionPermission requires
    a session younger than SESSION_SENSITIVE_ACTIONS_AGE and 403s with
    `sensitive_action_required_reauth` otherwise - the same re-auth modal the UI shows. Personal API
    keys skip the check entirely (the permission returns early for non-session auth), which is why
    this only applies to --session-id. The window is reported by the API as
    `sensitive_session_expires_at`; a null value means no window at all, usually a pending step-up.
    """
    raw_expiry = me.get("sensitive_session_expires_at")
    reauth_advice = (
        "Prefer --personal-api-key, which isn't subject to this window at all. Otherwise "
        "re-authenticate in the browser and copy the NEW sessionid: re-auth calls "
        "session.cycle_key(), specifically so a cookie copied beforehand stops working."
    )
    if not raw_expiry:
        raise PostHogScriptError(
            f"{printable(email)}'s session has no sensitive-action window, so every write would 403 "
            f"with sensitive_action_required_reauth. Usually a pending step-up re-auth. {reauth_advice}"
        )
    try:
        expires_at = datetime.datetime.fromisoformat(str(raw_expiry))
    except ValueError as err:
        raise PostHogScriptError(f"Could not parse sensitive_session_expires_at {printable(str(raw_expiry))}") from err

    remaining = (expires_at - datetime.datetime.now(datetime.UTC)).total_seconds()
    if remaining <= 0:
        raise PostHogScriptError(
            f"{printable(email)}'s sensitive-action window closed at {expires_at.isoformat()}, so "
            f"every write would 403 with sensitive_action_required_reauth. {reauth_advice}"
        )
    if remaining < SENSITIVE_WINDOW_WARN_SECONDS:
        log(
            f"WARNING: sensitive-action window closes in {int(remaining // 60)}m "
            f"({expires_at.isoformat()}). Long runs will start 403ing partway through."
        )


def resolve_user(session: requests.Session, host: str, email: str) -> dict[str, Any]:
    """Look up one user by exact email, returning the API row (uuid + notification_settings).

    Raises PostHogScriptError when the email matches no user, so the caller can record it as
    unresolved and carry on with the rest of the list.
    """
    url = f"{host}/api/users/?{urlencode({'email': email})}"
    response = request_with_retries(session, "GET", url)
    if response.status_code == 403:
        raise PostHogScriptError(f"forbidden (HTTP 403): {printable(response.text[:200])}")
    if response.status_code != 200:
        raise PostHogScriptError(f"lookup failed (HTTP {response.status_code}): {printable(response.text[:200])}")

    results: list[dict[str, Any]] = response.json().get("results") or []
    # The filter is a server-side exact match, but emails aren't guaranteed lowercase, so
    # re-check case-insensitively rather than trusting whatever the filter returned.
    exact = [row for row in results if str(row.get("email", "")).lower() == email.lower()]
    if not exact:
        raise PostHogScriptError("no user with that email")
    if len(exact) > 1:
        raise PostHogScriptError(f"{len(exact)} users share that email; resolve by UUID manually")
    row = exact[0]
    if not row.get("uuid"):
        raise PostHogScriptError("user row has no uuid")
    return row


def current_value(settings: dict[str, Any], setting: NotificationSetting, scope: Optional[str]) -> Any:
    """Read the user's effective value for this setting, or None when it isn't configured.

    The API already merges NOTIFICATION_DEFAULTS into `notification_settings`, so an unscoped key
    is always present. Scoped keys are absent until the user (or this script) writes them.
    """
    if setting.scope is None:
        return settings.get(setting.key)
    container = settings.get(setting.key) or {}
    if not isinstance(container, dict):
        return None
    if setting.scope == SCOPE_TYPE_TEAM:
        assert scope is not None  # guaranteed by parse_args
        type_key, team_id = scope.split(":", 1)
        per_type = container.get(type_key) or {}
        return per_type.get(team_id) if isinstance(per_type, dict) else None
    return container.get(scope)


def build_payload(setting: NotificationSetting, scope: Optional[str], desired: Any) -> dict[str, Any]:
    """Build the minimal notification_settings body; the API merges it over existing settings."""
    if setting.scope is None:
        value: Any = desired
    elif setting.scope == SCOPE_TYPE_TEAM:
        assert scope is not None  # guaranteed by parse_args
        type_key, team_id = scope.split(":", 1)
        value = {type_key: {team_id: desired}}
    else:
        assert scope is not None  # guaranteed by parse_args
        value = {scope: desired}
    return {"notification_settings": {setting.key: value}}


def plan_changes(
    session: requests.Session,
    host: str,
    emails: list[str],
    setting: NotificationSetting,
    scope: Optional[str],
    desired: Any,
) -> tuple[list[PlannedChange], list[str]]:
    """Resolve every email to a user and compute its before/after. Returns (planned, unresolved)."""
    planned: list[PlannedChange] = []
    unresolved: list[str] = []
    for email in emails:
        try:
            row = resolve_user(session, host, email)
        except PostHogScriptError as err:
            unresolved.append(f"{email}: {err}")
            continue
        settings = row.get("notification_settings") or {}
        current = current_value(settings, setting, scope)
        planned.append(
            PlannedChange(
                email=str(row.get("email") or email),
                uuid=str(row["uuid"]),
                current=current,
                desired=desired,
                clears_auto_select=setting.key in AUTO_SELECT_KEYS and current is None,
            )
        )
    return planned, unresolved


def apply_changes(
    session: requests.Session,
    host: str,
    changes: list[PlannedChange],
    payload: dict[str, Any],
    batch_size: int,
) -> tuple[Counter[str], list[str]]:
    """PATCH each user in turn; there is no bulk endpoint.

    Returns (status_counts, failures), keyed by HTTP status as a string plus an "error" bucket for
    requests that never got a response. Only 2xx counts as applied.
    """
    status_counts: Counter[str] = Counter()
    failures: list[str] = []
    total = len(changes)
    batch_counts: Counter[str] = Counter()
    batch_start = 1
    for index, change in enumerate(changes, start=1):
        url = f"{host}/api/users/{change.uuid}/"
        try:
            response = request_with_retries(session, "PATCH", url, json=payload)
        except PostHogScriptError as err:
            status_counts["error"] += 1
            batch_counts["error"] += 1
            failures.append(f"{change.email} ({change.uuid}): {err}")
        else:
            code = response.status_code
            status_counts[str(code)] += 1
            batch_counts[str(code)] += 1
            if not 200 <= code < 300:
                failures.append(f"{change.email} ({change.uuid}): HTTP {code} {response.text[:200]}")
        if index % batch_size == 0 or index == total:
            log(f"  updates {batch_start}-{index} of {total}: {format_status_counts(batch_counts)}")
            batch_counts = Counter()
            batch_start = index + 1
    return status_counts, failures


def validate_scope(parser: argparse.ArgumentParser, setting: NotificationSetting, scope: Optional[str]) -> None:
    """Reject a missing, unexpected, or malformed --scope before any request runs."""
    if setting.scope is None:
        if scope is not None:
            parser.error(f"--scope is not valid for {setting.key} (it stores a plain boolean)")
        return
    if scope is None:
        parser.error(f"--scope is required for {setting.key} (expects the {setting.scope} identifier)")

    if setting.scope == SCOPE_TEAM and not scope.isdigit():
        parser.error(f"--scope for {setting.key} must be a numeric project (team) ID, got {scope!r}")
    elif setting.scope == SCOPE_PIPELINE and not PIPELINE_ID_PATTERN.match(scope):
        parser.error(
            f"--scope for {setting.key} must look like hog_function:<id>, batch_export:<id> or "
            f"plugin_config:<id>, got {scope!r}"
        )
    elif setting.scope == SCOPE_TYPE_TEAM:
        if ":" not in scope:
            parser.error(f"--scope for {setting.key} must be <notification_type>:<team_id>, got {scope!r}")
        type_key, team_id = scope.split(":", 1)
        if type_key not in REALTIME_NOTIFICATION_TYPES:
            parser.error(f"unknown notification type {type_key!r}; see --list-settings for valid types")
        if not team_id.isdigit():
            parser.error(f"team ID in --scope must be numeric, got {team_id!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enable or disable one notification setting for a list of users, by email.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("emails", nargs="*", help="User email addresses to update")
    parser.add_argument("--emails-file", default=None, help="File of emails, one per line (# comments allowed)")
    parser.add_argument("--setting", default=None, help="Notification setting key (see --list-settings)")
    parser.add_argument(
        "--scope",
        default=None,
        help="Identifier for a scoped setting: project (team) ID, organization UUID, pipeline ID, "
        "or <notification_type>:<team_id>",
    )
    state = parser.add_mutually_exclusive_group()
    state.add_argument(
        "--enable", action="store_true", help="The user should receive this notification (polarity handled for you)"
    )
    state.add_argument("--disable", action="store_true", help="The user should not receive this notification")
    state.add_argument(
        "--value",
        type=float,
        default=None,
        help="Value for a number setting (e.g. data_pipeline_error_threshold); defaults to PostHog's default",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="Why this change is being made, ideally with a ticket link. Required for any run that "
        "writes; recorded in the plan, the prompt, the summary, and --output",
    )
    parser.add_argument(
        "--list-settings", action="store_true", help="Print every available setting and exit; needs no credentials"
    )
    # Env-backed args resolve after parsing so --help never prints API keys from the environment
    parser.add_argument(
        "--host",
        default=None,
        help="PostHog instance URL, or region shorthand 'us'/'eu' for PostHog Cloud "
        "(env: POSTHOG_HOST, else https://us.posthog.com)",
    )
    parser.add_argument(
        "--personal-api-key",
        default=None,
        help="Staff personal API key (phx_...) with user:read and user:write (env: POSTHOG_PERSONAL_API_KEY)",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Your own staff browser `sessionid` cookie, as an alternative to --personal-api-key "
        "(an impersonated session cannot write here; env: POSTHOG_SESSION_ID)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report what would change; write nothing")
    parser.add_argument(
        "--batch-size", type=int, default=25, help="How many updates to group per reported status-code batch"
    )
    parser.add_argument("--output", help="Write the planned changes to this JSON file")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    if args.list_settings:
        return args

    args.host = resolve_host(args.host or os.environ.get("POSTHOG_HOST") or "https://us.posthog.com")

    # An explicit flag beats the ambient environment. Falling back to `flag or env` would let a
    # POSTHOG_PERSONAL_API_KEY that happens to be exported (CI, a dev sandbox) silently take over a
    # run where the operator deliberately passed --session-id, so the credential actually used
    # wouldn't be the one they chose. main() logs which one wins.
    explicit_key = args.personal_api_key is not None
    explicit_session = args.session_id is not None
    if explicit_key and explicit_session:
        parser.error("pass either --personal-api-key or --session-id, not both")
    if explicit_session:
        args.personal_api_key = None
    elif not explicit_key:
        args.personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")
        args.session_id = os.environ.get("POSTHOG_SESSION_ID")

    if not args.emails and not args.emails_file:
        parser.error("provide at least one email positionally or via --emails-file")
    if not args.setting:
        parser.error("--setting is required (use --list-settings to see the options)")
    if args.setting not in SETTINGS_BY_KEY:
        parser.error(f"unknown --setting {args.setting!r}; use --list-settings to see the options")

    args.reason = (args.reason or "").strip()
    # Only writes need a reason, so exploring a plan with --dry-run stays frictionless. The floor is
    # low but non-zero: enough to stop a reflexive `--reason x` becoming the ticket's only record.
    if not args.dry_run:
        if not args.reason:
            parser.error(
                "--reason is required to write (nothing server-side records that staff changed "
                "these settings, so this run is the only evidence). Include a ticket link."
            )
        if len(args.reason) < MIN_REASON_LENGTH:
            parser.error(
                f"--reason must be at least {MIN_REASON_LENGTH} characters and say why, e.g. "
                '"customer asked to stop all digests, ZD-12345"'
            )

    setting = SETTINGS_BY_KEY[args.setting]
    if setting.kind == KIND_NUMBER:
        if args.enable or args.disable:
            parser.error(f"{setting.key} takes --value, not --enable/--disable ({setting.summary})")
        if args.value is None:
            # Not an error: resetting to PostHog's default is the common support ask, and main()
            # logs the value it fell back to so the run is never ambiguous.
            args.value = setting.default
        low, high = setting.bounds or (0.0, 1.0)
        if not low <= args.value <= high:
            parser.error(f"--value for {setting.key} must be between {low} and {high}, got {args.value}")
    else:
        if args.value is not None:
            parser.error(f"{setting.key} is a toggle: use --enable or --disable, not --value")
        if not args.enable and not args.disable:
            parser.error("exactly one of --enable or --disable is required")

    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")
    if not args.personal_api_key and not args.session_id:
        parser.error(
            "either --personal-api-key (POSTHOG_PERSONAL_API_KEY) or --session-id (POSTHOG_SESSION_ID) is required"
        )

    validate_scope(parser, SETTINGS_BY_KEY[args.setting], args.scope)
    return args


def main() -> int:
    args = parse_args()
    if args.list_settings:
        list_settings()
        return 0

    setting = SETTINGS_BY_KEY[args.setting]
    if setting.kind == KIND_NUMBER:
        desired: Any = args.value
        defaulted = " (PostHog default, no --value given)" if args.value == setting.default else ""
        intent = f"SET to {json.dumps(desired)}{defaulted}"
    else:
        receives = bool(args.enable)
        desired = setting.raw_value_for(receives=receives)
        intent = (
            f"{'ENABLE' if receives else 'DISABLE'} - the user "
            f"{'receives' if receives else 'does not receive'} this notification"
        )
    emails = read_emails(args.emails, args.emails_file)
    payload = build_payload(setting, args.scope, desired)

    session = requests.Session()
    if args.personal_api_key:
        log("Credential: personal API key (not subject to the sensitive-action re-auth window)")
        session.headers["Authorization"] = f"Bearer {args.personal_api_key}"
    else:
        log("Credential: browser session cookie (subject to the sensitive-action re-auth window)")
        setup_session_auth(session, args.host, args.session_id)
    acting_email = verify_staff_credential(session, args.host, session_auth=not args.personal_api_key)
    started_at = datetime.datetime.now(datetime.UTC).isoformat()

    scope_desc = f" scope={args.scope}" if args.scope else ""
    log("")
    log(f"Setting:  {setting.key}{scope_desc}")
    log(f"Intent:   {intent}")
    log(f"Reason:   {printable(args.reason) if args.reason else '(none - dry run)'}")
    log(f"Operator: {printable(acting_email)} at {started_at}")
    log(f"Writes:   {json.dumps(payload)}")
    log(f"Resolving {len(emails)} email(s) on {args.host}")

    planned, unresolved = plan_changes(session, args.host, emails, setting, args.scope, desired)
    to_change = [change for change in planned if not change.is_noop]
    noops = [change for change in planned if change.is_noop]

    log("")
    log(f"Resolved {len(planned)}/{len(emails)} email(s): {len(to_change)} to change, {len(noops)} already set.")

    if unresolved:
        log("")
        log(f"Unresolved ({len(unresolved)}) - skipped:")
        for entry in unresolved[:20]:
            log(f"  {printable(entry)}")
        if len(unresolved) > 20:
            log(f"  ... and {len(unresolved) - 20} more")

    if to_change:
        log("")
        log("Planned changes:")
        for change in to_change[:10]:
            log(
                f"  {printable(change.email)}  {change.uuid}  "
                f"{format_current(change.current)} -> {json.dumps(change.desired)}"
            )
        if len(to_change) > 10:
            log(f"  ... and {len(to_change) - 10} more (use --output to save the full list)")

    clearing = [change for change in to_change if change.clears_auto_select]
    if clearing:
        log("")
        log(
            f"Note: {len(clearing)} user(s) have {setting.key} unset. While it is unset, the first digest "
            "auto-enrolls their busiest project; writing an explicit value ends that, so projects you "
            "don't name here stay excluded."
        )

    if args.output:
        with open(args.output, "w") as f:
            json.dump(
                {
                    "host": args.host,
                    "reason": args.reason or None,
                    "operator": acting_email,
                    "started_at": started_at,
                    "dry_run": bool(args.dry_run),
                    "setting": setting.key,
                    "scope": args.scope,
                    "intent": intent,
                    "desired": desired,
                    "payload": payload,
                    "changes": [
                        {
                            "email": change.email,
                            "uuid": change.uuid,
                            "current": change.current,
                            "desired": change.desired,
                            "is_noop": change.is_noop,
                        }
                        for change in planned
                    ],
                    "unresolved": unresolved,
                },
                f,
                indent=2,
            )
        log(f"Wrote plan to {args.output}")

    if not to_change:
        log("")
        log("Nothing to change.")
        return 1 if unresolved else 0

    if args.dry_run:
        log("")
        log("DRY RUN: no changes made.")
        # Still non-zero on unresolved emails, so a scripted dry run fails on a bad list
        # instead of looking like a clean plan.
        return 1 if unresolved else 0

    if not args.yes:
        prompt = (
            f"\nAbout to change {setting.key} for {len(to_change)} user(s) on {args.host}, "
            f'because: "{printable(args.reason)}". '
            "These are other people's account settings - type 'toggle' to continue: "
        )
        if not confirm(
            prompt,
            "toggle",
            eof_message="Confirmation requires interactive input; pass --yes for non-interactive runs.",
        ):
            log("Aborted.")
            return 1

    status_counts, failures = apply_changes(session, args.host, to_change, payload, args.batch_size)
    updated = sum(n for code, n in status_counts.items() if code.isdigit() and 200 <= int(code) < 300)
    log("")
    log(f"Done: {updated}/{len(to_change)} updated. Status breakdown: {format_status_counts(status_counts)}")
    forbidden = status_counts.get("403", 0)
    if forbidden:
        log(
            f"  {forbidden} forbidden (HTTP 403): most likely sensitive_action_required_reauth - a "
            "session's sensitive-action window closing mid-run (see the message above; use "
            "--personal-api-key to avoid it). Otherwise the credential lost staff access, or an "
            "impersonation session was started - /api/users/ rejects writes while impersonating."
        )
    for failure in failures[:20]:
        log(f"  FAILED: {printable(failure)}")
    if len(failures) > 20:
        log(f"  ... and {len(failures) - 20} more failures")

    # Repeat the record at the end so the terminal transcript is pasteable into the ticket even
    # when --output wasn't used. Nothing server-side ties this change to the operator.
    log("")
    log("For the ticket - this is the only record of the change:")
    log(f"  operator: {printable(acting_email)}")
    log(f"  started:  {started_at}")
    log(f"  setting:  {setting.key}{scope_desc} -> {json.dumps(desired)}")
    log(f"  reason:   {printable(args.reason)}")
    if not args.output:
        log("  (pass --output <file>.json next time to save the full per-user list)")

    if failures or unresolved:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PostHogScriptError as err:
        log(f"Error: {printable(str(err))}")
        sys.exit(1)
    except KeyboardInterrupt:
        log("\nInterrupted.")
        sys.exit(130)
