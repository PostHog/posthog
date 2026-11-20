import re
from collections.abc import Collection, Mapping
from typing import Any

import requests

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

MAX_DISCUSSION_PAGES = 3
MAX_FAILED_JOBS = 20
MAX_JOB_LOGS = 3
JOB_LOG_TAIL_CHARS = 4000
# Escape codes and section markers take space that the cleaned excerpt drops.
JOB_LOG_TAIL_BYTES = JOB_LOG_TAIL_CHARS * 4
MAX_JOB_LOG_READ_BYTES = 16 * 1024 * 1024
MAX_MEMBER_LOOKUPS = 10
MAX_NOTES_FOR_DRAFT_HISTORY = 100
PIPELINE_FAILING_CHECK_KEY = "pipeline-failed"
# GitLab notes carry no author association, so members with Developer access or more get this one.
DEVELOPER_ASSOCIATION = "DEVELOPER"

_PIPELINE_CI_STATUS = {
    "success": "passing",
    "failed": "failing",
    "created": "pending",
    "waiting_for_resource": "pending",
    "waiting_for_callback": "pending",
    "preparing": "pending",
    "pending": "pending",
    "running": "pending",
    "scheduled": "pending",
}
# GitLab has not finished computing mergeability in these states, so neither a conflict nor a clean merge is known.
_UNSETTLED_MERGE_STATUSES = frozenset({"unchecked", "checking", "preparing", "approvals_syncing"})
_DRAFT_PREFIX_RE = re.compile(r"^\s*(?:(?:\[draft\]|\(draft\)|draft:|draft\s+-|\[wip\]|wip:)\s*)+", re.IGNORECASE)
# The system notes GitLab writes when a person toggles draft, including the older "Work In Progress" wording.
_DRAFT_TOGGLE_NOTE_RE = re.compile(
    r"marked (?:this merge request )?as (?:a )?\*\*(?:draft|ready|work in progress)\*\*", re.IGNORECASE
)
# Project and group access tokens act as these bot users. Their plain comments are automation chatter.
_BOT_USERNAME_RE = re.compile(r"^(?:project|group)_\d+_bot")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LOG_SECTION_RE = re.compile(r"section_(?:start|end):\d+:[^\r\n]*?\r")


@frozen
class _Feedback:
    threads: list[dict[str, Any]]
    comments: list[dict[str, Any]]


def parse_merge_request_iid(url: str, hostname: str, project_path: str) -> int | None:
    """The iid of a merge request URL in the connected project, or None for any other URL."""
    if not hostname or not project_path:
        return None
    match = re.fullmatch(
        re.escape(f"{hostname.rstrip('/')}/{project_path}") + r"/-/merge_requests/([1-9][0-9]{0,9})/?",
        url.strip(),
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def without_draft_prefix(title: str) -> str:
    return _DRAFT_PREFIX_RE.sub("", title).strip() or title.strip()


def clean_job_log(text: str) -> str:
    """The readable end of a job log: no color codes, no collapsible-section markers, and no partial first line."""
    text = _LOG_SECTION_RE.sub("", _ANSI_ESCAPE_RE.sub("", text))
    # A carriage return redraws the line in a terminal, so only the text after the last one is visible.
    text = "\n".join(line.rsplit("\r", 1)[-1] for line in text.split("\n")).strip()
    if len(text) > JOB_LOG_TAIL_CHARS:
        text = text[-JOB_LOG_TAIL_CHARS:]
        text = text[text.find("\n") + 1 :]
    return text


def _merge_request_state(mr: Mapping[str, Any]) -> str:
    state = mr.get("state")
    if state == "merged":
        return "merged"
    if state in ("closed", "locked"):
        return "closed"
    if state == "opened":
        return "draft" if _is_draft(mr) else "open"
    return "unknown"


def _is_draft(mr: Mapping[str, Any]) -> bool:
    return mr.get("draft") is True or mr.get("work_in_progress") is True


def _username(note: Mapping[str, Any]) -> str | None:
    username = (note.get("author") or {}).get("username")
    return username if isinstance(username, str) else None


class GitLabMergeRequestClient:
    """The GitLab side of the PR follow-up loop for one merge request.

    It answers in the raw shape of the GitHub client's ``get_pull_request_babysit_snapshot`` and
    ``mark_pull_request_ready_for_review``, so ``PRSnapshot.from_raw``, the attention journal and the
    wake prompt work for both providers.
    """

    def __init__(self, gitlab: GitLabIntegration, project_id: int, pr_url: str, iid: int) -> None:
        self._gitlab = gitlab
        self._project_id = project_id
        self.pr_url = pr_url
        self.iid = iid

    @classmethod
    def load(cls, team_id: int, integration_id: int, pr_url: str) -> "GitLabMergeRequestClient | None":
        """None when ``pr_url`` is not a merge request of the connection's project.

        Raises ``IntegrationNotFound`` when the connection is gone.
        """
        gitlab = GitLabIntegration(IntegrationManager.gitlab.token.get(team_id, integration_id))
        project_id = gitlab.integration.config.get("project_id")
        iid = parse_merge_request_iid(pr_url, gitlab.hostname or "", gitlab.project_path or "")
        if iid is None or project_id is None:
            return None
        return cls(gitlab, int(project_id), pr_url, iid)

    def get_babysit_snapshot(self) -> dict[str, Any]:
        mr = self._gitlab.get_merge_request_details(self._project_id, self.iid)
        if mr is None:
            return {"success": False, "error": "Merge request not found"}
        author_login = _username(mr)
        web_url = mr.get("web_url") or self.pr_url
        raw: dict[str, Any] = {
            "success": True,
            # The run output stores this URL, and the ready check compares the snapshot against it.
            "url": self.pr_url,
            "state": _merge_request_state(mr),
            "head_sha": mr.get("sha") or "",
            "head_ref": mr.get("source_branch") or "",
            "author_login": author_login,
        }
        if raw["state"] in ("merged", "closed"):
            return raw

        discussions, complete = self._gitlab.list_merge_request_discussions(
            self._project_id, self.iid, max_pages=MAX_DISCUSSION_PAGES
        )
        feedback = self._feedback(discussions, author_login, web_url)
        ci_status, failing_checks = self._pipeline(mr)
        merge_status = mr.get("detailed_merge_status")
        has_conflict = mr.get("has_conflicts") is True or merge_status == "conflict"
        raw.update(
            has_conflict=has_conflict,
            mergeable=not has_conflict and merge_status not in _UNSETTLED_MERGE_STATUSES,
            ci_status=ci_status,
            review_decision="CHANGES_REQUESTED" if merge_status == "requested_changes" else None,
            review_threads_complete=complete,
            failing_checks=failing_checks,
            unresolved_threads=feedback.threads,
            comments=feedback.comments,
        )
        return raw

    def mark_ready(self, *, skip_labels: Collection[str], expected_head_sha: str | None) -> dict[str, Any]:
        """Same contract and guards as ``GitHubIntegrationBase.mark_pull_request_ready_for_review``.

        GitLab reads draft from the title prefix on every version, while the ``draft`` attribute of the update
        endpoint is not available on all of them, so this removes the prefix.
        """
        mr = self._gitlab.get_merge_request_details(self._project_id, self.iid)
        if mr is None:
            return {"success": False, "error": "Merge request not found"}
        if mr.get("state") != "opened":
            return {"success": True, "changed": False, "reason": "closed"}
        if not _is_draft(mr):
            return {"success": True, "changed": False, "reason": "not_draft"}
        if expected_head_sha is not None and mr.get("sha") != expected_head_sha:
            return {"success": True, "changed": False, "reason": "head_changed"}
        if self._draft_state_decided():
            return {"success": True, "changed": False, "reason": "draft_state_decided"}
        unwanted = {label.casefold() for label in skip_labels}
        if unwanted & {label.casefold() for label in mr.get("labels") or [] if isinstance(label, str)}:
            return {"success": True, "changed": False, "reason": "label"}
        self._gitlab.set_merge_request_title(self._project_id, self.iid, without_draft_prefix(mr.get("title") or ""))
        return {"success": True, "changed": True}

    def _draft_state_decided(self) -> bool:
        """Whether a person already moved the merge request between draft and ready.

        A merge request that opened as a draft has no such system note, so a note means its draft state is a
        choice that the runner must keep.
        """
        notes = self._gitlab.list_merge_request_notes(self._project_id, self.iid, limit=MAX_NOTES_FOR_DRAFT_HISTORY)
        return any(
            note.get("system") is True and _DRAFT_TOGGLE_NOTE_RE.search(str(note.get("body") or "")) for note in notes
        )

    def _feedback(self, discussions: list[dict[str, Any]], author_login: str | None, web_url: str) -> _Feedback:
        threads: list[dict[str, Any]] = []
        comments: list[dict[str, Any]] = []
        for discussion in discussions:
            notes = [note for note in discussion.get("notes") or [] if isinstance(note, dict)]
            if not notes or notes[0].get("system") is True:
                continue
            resolvable = [note for note in notes if note.get("resolvable") is True]
            if resolvable:
                if all(note.get("resolved") is True for note in resolvable):
                    continue
                last = notes[-1]
                threads.append(
                    {
                        "id": discussion.get("id"),
                        "last_comment_id": str(last.get("id") or ""),
                        "path": (notes[0].get("position") or {}).get("new_path"),
                        "author": _username(last),
                        "body": last.get("body"),
                        "url": f"{web_url}#note_{last.get('id')}",
                        "_author_id": (last.get("author") or {}).get("id"),
                    }
                )
            elif discussion.get("individual_note") is True:
                note = notes[0]
                username = _username(note)
                if note.get("id") is None or username == author_login or _BOT_USERNAME_RE.match(username or ""):
                    continue
                comments.append(
                    {
                        "id": str(note["id"]),
                        "author": username,
                        "body": note.get("body"),
                        "url": f"{web_url}#note_{note['id']}",
                        "_author_id": (note.get("author") or {}).get("id"),
                    }
                )
        items = [*threads, *comments]
        developers = self._developer_ids([item["_author_id"] for item in items if item.get("author") != author_login])
        for item in items:
            item["author_association"] = DEVELOPER_ASSOCIATION if item.pop("_author_id") in developers else None
        return _Feedback(threads=threads, comments=comments)

    def _developer_ids(self, author_ids: list[object]) -> set[int]:
        # The wake prompt trusts feedback by role, so an author past the lookup cap reads as untrusted.
        candidates = list(dict.fromkeys(author_id for author_id in author_ids if isinstance(author_id, int)))
        return {author_id for author_id in candidates[:MAX_MEMBER_LOOKUPS] if self._gitlab.is_developer(author_id)}

    def _pipeline(self, mr: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        pipeline = mr.get("head_pipeline")
        # GitLab keeps the previous pipeline as head_pipeline until one starts for the new commit.
        if not isinstance(pipeline, dict) or not pipeline.get("sha") or pipeline.get("sha") != mr.get("sha"):
            return "none", []
        status = pipeline.get("status")
        ci_status = _PIPELINE_CI_STATUS.get(status or "", "none")
        if status not in ("failed", "running") or not isinstance(pipeline.get("id"), int):
            return ci_status, []

        failing: list[dict[str, Any]] = []
        seen: set[str] = set()
        for job in self._gitlab.list_failed_pipeline_jobs(self._project_id, pipeline["id"], limit=MAX_FAILED_JOBS):
            name = job.get("name")
            if job.get("allow_failure") is True or not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            check: dict[str, Any] = {"key": name, "details_url": job.get("web_url")}
            if len(failing) < MAX_JOB_LOGS and isinstance(job.get("id"), int):
                check["log_excerpt"] = self._job_log_excerpt(job["id"])
            failing.append(check)
        if not failing and status == "failed":
            failing.append({"key": PIPELINE_FAILING_CHECK_KEY, "details_url": pipeline.get("web_url")})
        return ci_status, failing

    def _job_log_excerpt(self, job_id: int) -> str:
        # The job link is enough to act on, so a log that GitLab cannot serve must not fail the snapshot.
        try:
            tail = self._gitlab.get_job_log_tail(
                self._project_id, job_id, max_bytes=JOB_LOG_TAIL_BYTES, max_read_bytes=MAX_JOB_LOG_READ_BYTES
            )
        except (GitLabIntegrationError, requests.RequestException):
            return ""
        return clean_job_log(tail) if tail else ""
