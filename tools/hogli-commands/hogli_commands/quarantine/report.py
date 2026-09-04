"""Route quarantine entries that are at or past their expiry to their owners.

``check`` only tells whoever runs it, which on a pull request is the person
already editing ``.test_quarantine.json``. An entry that nobody edits therefore
lapses in silence, and the test it covers stays out of CI. This module builds a
digest of every entry near or past ``expires``, each row naming its ``owner``,
and reconciles it into one GitHub issue: created when something needs attention,
updated in place while it does, and closed once every entry is inside its
window. Owners are mentioned on creation and whenever an entry newly slips, so
the notification lands without a fresh issue on each run.

The rendering is pure and testable; ``gh`` runs only in ``open_issue`` and
``apply``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date

from hogli_commands.quarantine import core

ISSUE_TITLE = "Quarantined tests are due for removal or re-triage"
ISSUE_LABEL = "test-quarantine"
ISSUE_LABEL_COLOR = "d4c5f9"
ISSUE_LABEL_DESCRIPTION = "Automated digest of .test_quarantine.json entries near or past expiry"
CLOSE_COMMENT = "Every quarantine entry is inside its window again."

# The states worth telling an owner about, most urgent first.
REPORTABLE_STATES = (core.OVERDUE, core.IN_GRACE, core.EXPIRING_SOON)

_ORG = "PostHog"

# Lets a later run read back what the previous one reported, so a comment goes
# out only when an entry newly slips rather than on every update.
_STATE_MARKER = "<!-- quarantine-expiry-state:"

# Reasons run to several sentences, which makes the digest table unreadable.
_REASON_LIMIT = 120


@dataclass(frozen=True)
class Item:
    entry: core.Entry
    state: str
    days_expired: int


@dataclass(frozen=True)
class Report:
    items: list[Item]
    body: str
    comment: str | None


def collect(
    entries: list[core.Entry],
    today: date,
    grace_days: int = core.DEFAULT_GRACE_DAYS,
    soon_days: int = core.DEFAULT_SOON_DAYS,
) -> list[Item]:
    """Entries near or past expiry, most urgent first, then soonest, then id."""
    items: list[Item] = []
    for entry in entries:
        state = core.lifecycle(entry, today, grace_days, soon_days)
        if state in REPORTABLE_STATES:
            items.append(Item(entry=entry, state=state, days_expired=core.days_expired(entry, today)))
    return sorted(items, key=lambda i: (REPORTABLE_STATES.index(i.state), i.entry.expires, i.entry.id))


def mention(owner: str) -> str:
    """Render ``owner`` so that GitHub notifies it.

    Entries name GitHub team slugs (``@team-devex``), which only notify once
    qualified with the org. A value that already carries an org, and anything
    that is not a team slug, is left alone: a personal handle still mentions
    that person, and free text stays free text.
    """
    handle = owner.lstrip("@")
    if not handle or "/" in handle:
        return f"@{handle}" if handle else ""
    return f"@{_ORG}/{handle}" if handle.startswith("team-") else owner


def build_report(items: list[Item], previous_states: dict[str, str], grace_days: int, workflow_url: str = "") -> Report:
    return Report(items=items, body=_body(items, grace_days, workflow_url), comment=_comment(items, previous_states))


def read_states(body: str) -> dict[str, str]:
    """Recover the state map a previous run embedded in the issue body."""
    _, marker, rest = body.partition(_STATE_MARKER)
    if not marker:
        return {}
    payload, closer, _ = rest.partition("-->")
    if not closer:
        return {}
    try:
        states = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return states if isinstance(states, dict) else {}


def _body(items: list[Item], grace_days: int, workflow_url: str) -> str:
    sections = [
        _section(
            "Overdue",
            f"Past the {grace_days}-day grace period. `hogli test:quarantine check` fails until these are gone.",
            [i for i in items if i.state == core.OVERDUE],
        ),
        _section(
            "In the grace period",
            "Already expired, so the test blocks CI again. Removal becomes mandatory when the grace period ends.",
            [i for i in items if i.state == core.IN_GRACE],
        ),
        _section(
            "Expiring soon",
            "Still active. Fix the test, or re-triage the entry before it lapses.",
            [i for i in items if i.state == core.EXPIRING_SOON],
        ),
    ]
    lines = [
        "Each entry below is at or near its `expires` date in `.test_quarantine.json`.",
        "Remove the entry once the test is fixed, or re-triage it with a fresh window:",
        "",
        "```bash",
        "hogli test:quarantine remove '<id>'",
        "```",
        "",
        *[line for section in sections if section for line in (*section, "")],
        _footer(workflow_url),
        f"{_STATE_MARKER} {json.dumps({i.entry.id: i.state for i in items}, sort_keys=True)} -->",
    ]
    return "\n".join(lines)


def _section(title: str, blurb: str, items: list[Item]) -> list[str] | None:
    if not items:
        return None
    rows = [
        f"| {_test_cell(i)} | {i.entry.runner} | {mention(i.entry.owner)} | {_when(i)} | {_reason(i)} |" for i in items
    ]
    return [
        f"### {title} ({len(items)})",
        "",
        blurb,
        "",
        "| Test | Runner | Owner | Expiry | Reason |",
        "| --- | --- | --- | --- | --- |",
        *rows,
    ]


def _test_cell(item: Item) -> str:
    cell = f"`{item.entry.id}`"
    return f"[{cell}]({item.entry.issue})" if item.entry.issue else cell


def _reason(item: Item) -> str:
    reason = " ".join(item.entry.reason.split())
    return f"{reason[: _REASON_LIMIT - 1]}…" if len(reason) > _REASON_LIMIT else reason


def _when(item: Item) -> str:
    days = item.days_expired
    if days > 0:
        return f"expired {days}d ago ({item.entry.expires.isoformat()})"
    if days == 0:
        return f"expires today ({item.entry.expires.isoformat()})"
    return f"in {-days}d ({item.entry.expires.isoformat()})"


def _footer(workflow_url: str) -> str:
    source = f"[Test quarantine]({workflow_url})" if workflow_url else "the Test quarantine workflow"
    return f"<sub>Refreshed each weekday by {source}. It closes itself once every entry is inside its window.</sub>"


def _comment(items: list[Item], previous_states: dict[str, str]) -> str | None:
    slipped = [i for i in items if REPORTABLE_STATES.index(i.state) < _previous_rank(previous_states, i.entry.id)]
    if not slipped:
        return None
    lines = [f"- `{i.entry.id}` ({mention(i.entry.owner)}): {i.state}, {_when(i)}" for i in slipped]
    return "\n".join(["These entries moved closer to their deadline, or past it:", "", *lines])


def _previous_rank(previous_states: dict[str, str], entry_id: str) -> int:
    state = previous_states.get(entry_id)
    return REPORTABLE_STATES.index(state) if state in REPORTABLE_STATES else len(REPORTABLE_STATES)


def run(
    entries: list[core.Entry],
    today: date,
    *,
    repo: str,
    grace_days: int = core.DEFAULT_GRACE_DAYS,
    soon_days: int = core.DEFAULT_SOON_DAYS,
    workflow_url: str = "",
    dry_run: bool = False,
) -> tuple[Report, str]:
    """Build the digest and, unless ``dry_run``, reconcile it into the issue.

    A dry run still reads the open issue, so the preview names the action a
    real run would take, and the text it would post, rather than re-announcing
    every entry.
    """
    items = collect(entries, today, grace_days, soon_days)
    existing = open_issue(repo)
    previous = read_states(existing[1]) if existing else {}
    built = build_report(items, previous, grace_days, workflow_url)
    return built, preview(built, existing) if dry_run else apply(built, existing, repo)


def _gh(*args: str, repo: str, stdin: str | None = None) -> str:
    command = ["gh", *args, "--repo", repo]
    result = subprocess.run(command, input=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        # capture_output hides stderr, and "exit status 1" alone is unreadable in a CI log.
        raise RuntimeError(f"`{' '.join(args)}` failed: {result.stderr.strip() or result.returncode}")
    return result.stdout.strip()


def open_issue(repo: str) -> tuple[int, str] | None:
    """The digest issue a previous run opened, if it is still open.

    ``apply`` replaces the whole body of what this returns, and can close it.
    The label is not proof of ownership, because anybody can put it on any
    issue, so the state marker decides: only a run of this tool writes one. A
    labelled issue without the marker belongs to a person and stays untouched.
    Two marked issues mean the automation lost track of which one it owns, so
    it stops rather than pick one and leave owners reading a stale digest.
    """
    fields = ("--json", "number,body", "--limit", "50")
    raw = _gh("issue", "list", "--state", "open", "--label", ISSUE_LABEL, *fields, repo=repo)
    issues = [i for i in json.loads(raw or "[]") if _STATE_MARKER in (i["body"] or "")]
    if len(issues) > 1:
        numbers = ", ".join(f"#{i['number']}" for i in issues)
        raise RuntimeError(f"{len(issues)} open issues hold the digest state marker ({numbers}); close all but one")
    return (issues[0]["number"], issues[0]["body"] or "") if issues else None


def apply(report: Report, existing: tuple[int, str] | None, repo: str) -> str:
    """Create, update, or close the digest issue. Returns what it did."""
    if not report.items:
        if existing is None:
            return "nothing to report"
        _gh("issue", "close", str(existing[0]), "--comment", CLOSE_COMMENT, repo=repo)
        return f"closed #{existing[0]}"

    if existing is None:
        label = ("--description", ISSUE_LABEL_DESCRIPTION, "--color", ISSUE_LABEL_COLOR, "--force")
        _gh("label", "create", ISSUE_LABEL, *label, repo=repo)
        create = ("--title", ISSUE_TITLE, "--label", ISSUE_LABEL, "--body-file", "-")
        url = _gh("issue", "create", *create, repo=repo, stdin=report.body)
        return f"opened {url}"

    number = existing[0]
    _gh("issue", "edit", str(number), "--body-file", "-", repo=repo, stdin=report.body)
    if report.comment is None:
        return f"updated #{number}"
    _gh("issue", "comment", str(number), "--body-file", "-", repo=repo, stdin=report.comment)
    return f"updated #{number} and notified owners"


def preview(report: Report, existing: tuple[int, str] | None) -> str:
    """What ``apply`` would do, and the text it would post, without writing.

    The branches mirror ``apply``, because a preview that only rendered the
    digest would show nothing for an all-clear run, which in fact closes the
    issue. Creation drops the comment, so this drops it too: the new body
    already mentions every owner.
    """
    if not report.items:
        if existing is None:
            return "nothing to report"
        return f"would close #{existing[0]}\n\n{CLOSE_COMMENT}"
    if existing is None:
        return f"would open a new issue\n\n{report.body}"
    if report.comment is None:
        return f"would update #{existing[0]}\n\n{report.body}"
    return f"would update #{existing[0]} and notify owners\n\n{report.body}\n\n--- comment ---\n{report.comment}"
