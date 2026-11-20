import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError

from products.review_hog.backend.app_identity import posthog_app_login
from products.review_hog.backend.facade.contracts import ForkRecreationOutcome
from products.review_hog.backend.reviewer.tools.github_client import matches_app_bot

logger = structlog.get_logger(__name__)

WRITE_PERMISSIONS = frozenset({"admin", "maintain", "write"})
VERDICT_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})
MERGE_QUEUE_LABEL = "trunk-merge-queue-submit"
FORK_PR_MARKER = "<!-- fork-pr: {number} @{login} -->"
RECREATED_MARKER = "<!-- fork-pr-recreated -->"
CI_PATH_PREFIXES = (".github/", ".depot/", "bin/")
CI_FILE_NAMES = frozenset({"package.json", "conftest.py"})
MAX_COMPARE_FILES = 300
GRAPHQL_PATHS_PER_QUERY = 100
MAX_COMMENT_PAGES = 10
_SOURCE = "review_hog_fork_recreation"
_CALL_ERRORS = (GitHubIntegrationError, GitHubRateLimitError, requests.RequestException)
_MENTION_RE = re.compile(r"@(?=[A-Za-z0-9])")
_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


class RecreationRefused(Exception):
    pass


class RecreationFailed(Exception):
    pass


@frozen
class Approval:
    login: str
    user_id: int
    commit_sha: str


@frozen
class Contributor:
    login: str
    user_id: int
    name: str

    @property
    def noreply_email(self) -> str:
        return f"{self.user_id}+{self.login}@users.noreply.github.com"


@frozen
class ChangedFile:
    path: str
    status: Literal["added", "modified", "removed", "renamed", "copied", "changed", "unchanged"]
    previous_path: str | None = None


@frozen
class TreeEntry:
    path: str
    mode: str
    type: Literal["blob", "commit"]
    sha: str | None


def latest_approvals(reviews: Sequence[Mapping[str, Any]]) -> list[Approval]:
    latest: dict[int, Mapping[str, Any]] = {}
    for review in reviews:
        user = review.get("user") or {}
        if review.get("state") in VERDICT_STATES and isinstance(user.get("id"), int):
            latest[user["id"]] = review
    approved = [
        review
        for review in latest.values()
        if review["state"] == "APPROVED" and isinstance(review.get("commit_id"), str)
    ]
    approved.sort(key=lambda review: str(review.get("submitted_at") or ""), reverse=True)
    return [
        Approval(login=review["user"]["login"], user_id=review["user"]["id"], commit_sha=review["commit_id"])
        for review in approved
        if not review["user"]["login"].endswith("[bot]")
    ]


def co_author_trailers(contributor: Contributor, commits: Iterable[Mapping[str, Any]]) -> list[str]:
    authors = [contributor]
    for commit in commits:
        account = commit.get("author") or {}
        if len(commit.get("parents") or []) > 1 or not isinstance(account.get("id"), int):
            continue
        login = account.get("login")
        if isinstance(login, str) and _LOGIN_RE.fullmatch(login):
            authors.append(Contributor(login=login, user_id=account["id"], name=login))
    unique = {author.user_id: author for author in reversed(authors)}
    ordered = [contributor, *(author for author in unique.values() if author.user_id != contributor.user_id)]
    return [f"Co-authored-by: {_plain(author.name)} <{author.noreply_email}>" for author in ordered]


def _plain(name: str) -> str:
    return "".join(char for char in name if char.isprintable() and char not in "<>") or "unknown"


def neutralise_mentions(text: str) -> str:
    return _MENTION_RE.sub("@\u200b", text)


def changed_files(files: Sequence[Mapping[str, Any]]) -> list[ChangedFile]:
    return [
        ChangedFile(path=file["filename"], status=file["status"], previous_path=file.get("previous_filename"))
        for file in files
    ]


def touched_paths(files: Sequence[ChangedFile]) -> list[str]:
    paths = [file.path for file in files]
    paths += [file.previous_path for file in files if file.previous_path]
    return list(dict.fromkeys(paths))


def ci_paths(paths: Iterable[str]) -> list[str]:
    def runs_in_ci(path: str) -> bool:
        lowered = path.lower()
        name = lowered.rpartition("/")[2]
        return lowered.startswith(CI_PATH_PREFIXES) or name in CI_FILE_NAMES or name.startswith("dockerfile")

    return [path for path in paths if runs_in_ci(path)]


def tree_entries(files: Sequence[ChangedFile], head_entries: Mapping[str, TreeEntry]) -> list[TreeEntry]:
    entries: list[TreeEntry] = []
    for file in files:
        if file.status == "renamed" and file.previous_path:
            entries.append(TreeEntry(path=file.previous_path, mode="100644", type="blob", sha=None))
        if file.status == "removed":
            entries.append(TreeEntry(path=file.path, mode="100644", type="blob", sha=None))
            continue
        entry = head_entries.get(file.path)
        if entry is None:
            raise RecreationFailed(f"The approved commit has no entry for {file.path}")
        entries.append(entry)
    return entries


def _octal_mode(mode: int) -> str:
    return format(mode, "o").rjust(6, "0")


def _parent(path: str) -> str:
    return path.rpartition("/")[0]


def _graphql_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class ForkRecreation:
    def __init__(
        self,
        github: GitHubIntegration,
        repository: str,
        pr_number: int,
        *,
        app_login: str | None,
        enqueue: bool = False,
    ) -> None:
        self._github = github
        self._app_login = app_login
        self._repository = repository
        self._owner, self._name = repository.split("/", 1)
        self._pr_number = pr_number
        self._enqueue = enqueue

    def run(self) -> ForkRecreationOutcome:
        fork_pr = self._get(
            f"/repos/{self._repository}/pulls/{self._pr_number}", "/repos/{owner}/{repo}/pulls/{pull_number}"
        )
        default_branch = fork_pr["base"]["repo"]["default_branch"]
        self._refuse_unless_recreatable(fork_pr, default_branch)

        approval = self._approval()
        branch = f"fork-pr/{self._pr_number}"
        if self._ref_exists(branch):
            existing = self._open_pull_request_from(branch)
            if existing is None:
                raise RecreationRefused(
                    f"The branch `{branch}` already exists with no open pull request. Delete the branch to re-create it."
                )
            if not matches_app_bot(existing.get("user"), self._app_login):
                raise RecreationRefused(
                    f"The open pull request from `{branch}` wasn't opened by PostHog, so I won't hand this one over to it."
                )
            contributor = self._contributor(fork_pr["user"]["login"])
            return self._outcome(existing, self._hand_over(existing["number"], approval, contributor, fork_pr))

        base_sha = self._get(
            f"/repos/{self._repository}/git/ref/heads/{default_branch}", "/repos/{owner}/{repo}/git/ref/{ref}"
        )["object"]["sha"]
        base_tree_sha = self._get(
            f"/repos/{self._repository}/git/commits/{base_sha}", "/repos/{owner}/{repo}/git/commits/{commit_sha}"
        )["tree"]["sha"]
        comparison = self._get(
            f"/repos/{self._repository}/compare/{base_sha}...{approval.commit_sha}",
            "/repos/{owner}/{repo}/compare/{basehead}",
        )
        files = changed_files(comparison.get("files") or [])
        if not files:
            raise RecreationRefused(
                "The approved commit changes nothing on the default branch. It may already have landed."
            )
        if len(files) >= MAX_COMPARE_FILES:
            raise RecreationRefused(
                f"The approved commit changes {MAX_COMPARE_FILES} files or more, more than GitHub lists. Re-create it by hand."
            )
        paths = touched_paths(files)
        if ci_paths(paths):
            raise RecreationRefused(
                "The approved commit changes files CI runs, such as workflows, scripts, `package.json` or Dockerfiles. "
                "Re-create it by hand."
            )

        merge_base_sha = comparison["merge_base_commit"]["sha"]
        conflicts = self._paths_changed_since(merge_base_sha, base_sha, paths)
        if conflicts:
            raise RecreationRefused(
                f"{len(conflicts)} changed files also changed on the default branch since the fork branched. "
                "Ask the contributor to merge the default branch into their branch, approve the new commit, then comment again."
            )

        head_entries = self._entries_at(approval.commit_sha, [file.path for file in files if file.status != "removed"])
        contributor = self._contributor(fork_pr["user"]["login"])
        tree_sha = self._post(
            f"/repos/{self._repository}/git/trees",
            "/repos/{owner}/{repo}/git/trees",
            {
                "base_tree": base_tree_sha,
                "tree": [
                    {"path": entry.path, "mode": entry.mode, "type": entry.type, "sha": entry.sha}
                    for entry in tree_entries(files, head_entries)
                ],
            },
        )["sha"]
        trailers = co_author_trailers(contributor, comparison.get("commits") or [])
        message = "\n".join(
            [
                f"{neutralise_mentions(fork_pr['title'])} (#{self._pr_number})",
                "",
                f"Re-created from #{self._pr_number} at {approval.commit_sha}.",
                "",
                *trailers,
            ]
        )
        commit_sha = self._post(
            f"/repos/{self._repository}/git/commits",
            "/repos/{owner}/{repo}/git/commits",
            {"message": message, "tree": tree_sha, "parents": [base_sha]},
        )["sha"]
        self._post(
            f"/repos/{self._repository}/git/refs",
            "/repos/{owner}/{repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )

        try:
            new_pr = self._post(
                f"/repos/{self._repository}/pulls",
                "/repos/{owner}/{repo}/pulls",
                {
                    "title": neutralise_mentions(fork_pr["title"]),
                    "head": branch,
                    "base": default_branch,
                    "body": self._body(fork_pr, approval, contributor, trailers),
                    "maintainer_can_modify": True,
                },
            )
        except RecreationFailed:
            self._delete_branch(branch)
            raise

        return self._outcome(new_pr, self._hand_over(new_pr["number"], approval, contributor, fork_pr))

    def _outcome(self, pull_request: Mapping[str, Any], handed_over: bool) -> ForkRecreationOutcome:
        return ForkRecreationOutcome(
            created=True,
            message="",
            pull_request_number=pull_request["number"],
            pull_request_url=pull_request["html_url"],
            handed_over=handed_over,
        )

    def _open_pull_request_from(self, branch: str) -> Mapping[str, Any] | None:
        response = self._request(
            "GET",
            f"/repos/{self._repository}/pulls?head={self._owner}:{branch}&state=open",
            "/repos/{owner}/{repo}/pulls",
        )
        if response.status_code != 200:
            raise RecreationFailed(f"GitHub answered {response.status_code} listing pull requests")
        pulls = response.json()
        return pulls[0] if pulls else None

    def _refuse_unless_recreatable(self, fork_pr: Mapping[str, Any], default_branch: str) -> None:
        head_repo = (fork_pr.get("head") or {}).get("repo") or {}
        if head_repo.get("full_name", "").lower() == self._repository.lower():
            raise RecreationRefused("This pull request is already on a branch in this repository.")
        if fork_pr.get("state") != "open":
            raise RecreationRefused("This pull request is closed.")
        if fork_pr["base"]["ref"] != default_branch:
            raise RecreationRefused("Only pull requests into the default branch can be re-created.")

    def _approval(self) -> Approval:
        try:
            reviews = self._github.get_pull_request_reviews(self._repository, self._pr_number)
        except _CALL_ERRORS as error:
            raise RecreationFailed("GitHub did not answer the review lookup") from error
        unverified = 0
        for approval in latest_approvals(reviews):
            try:
                permission = self._github.get_collaborator_permission(
                    self._repository, approval.login, expected_user_id=approval.user_id
                )
            except _CALL_ERRORS:
                logger.warning("fork_recreation_permission_lookup_failed", repository=self._repository, exc_info=True)
                unverified += 1
                continue
            if permission in WRITE_PERMISSIONS:
                return approval
        if unverified:
            raise RecreationFailed("GitHub did not answer a permission lookup")
        raise RecreationRefused(
            "No one with write access has approved this pull request. Approve the commit you reviewed, then comment again."
        )

    def _contributor(self, login: str) -> Contributor:
        user = self._get(f"/users/{login}", "/users/{username}")
        return Contributor(login=user["login"], user_id=user["id"], name=user.get("name") or user["login"])

    def _ref_exists(self, branch: str) -> bool:
        response = self._request(
            "GET", f"/repos/{self._repository}/git/ref/heads/{branch}", "/repos/{owner}/{repo}/git/ref/{ref}"
        )
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise RecreationFailed(f"GitHub answered {response.status_code} reading the branch")
        return True

    def _paths_changed_since(self, merge_base_sha: str, base_sha: str, paths: Sequence[str]) -> list[str]:
        changed: list[str] = []
        for start in range(0, len(paths), GRAPHQL_PATHS_PER_QUERY):
            chunk = paths[start : start + GRAPHQL_PATHS_PER_QUERY]
            fields = []
            for index, path in enumerate(chunk):
                fields.append(f"b{index}: object(expression: {_graphql_string(f'{merge_base_sha}:{path}')}) {{ oid }}")
                fields.append(f"h{index}: object(expression: {_graphql_string(f'{base_sha}:{path}')}) {{ oid }}")
            repository = self._graphql(fields)
            for index, path in enumerate(chunk):
                before = (repository.get(f"b{index}") or {}).get("oid")
                after = (repository.get(f"h{index}") or {}).get("oid")
                if before != after:
                    changed.append(path)
        return changed

    def _entries_at(self, commit_sha: str, paths: Sequence[str]) -> dict[str, TreeEntry]:
        directories = list(dict.fromkeys(_parent(path) for path in paths))
        entries: dict[str, TreeEntry] = {}
        for start in range(0, len(directories), GRAPHQL_PATHS_PER_QUERY):
            chunk = directories[start : start + GRAPHQL_PATHS_PER_QUERY]
            fields = [
                f"d{index}: object(expression: {_graphql_string(f'{commit_sha}:{directory}')}) "
                "{ ... on Tree { entries { name mode oid type } } }"
                for index, directory in enumerate(chunk)
            ]
            repository = self._graphql(fields)
            for index, directory in enumerate(chunk):
                for entry in (repository.get(f"d{index}") or {}).get("entries") or []:
                    path = f"{directory}/{entry['name']}" if directory else entry["name"]
                    if entry["type"] in ("blob", "commit"):
                        entries[path] = TreeEntry(
                            path=path, mode=_octal_mode(entry["mode"]), type=entry["type"], sha=entry["oid"]
                        )
        return entries

    def _body(
        self, fork_pr: Mapping[str, Any], approval: Approval, contributor: Contributor, trailers: Sequence[str]
    ) -> str:
        description = neutralise_mentions(fork_pr.get("body") or "_No description._")
        quoted = "\n".join(f"> {line}" for line in description.splitlines())
        return "\n".join(
            [
                FORK_PR_MARKER.format(number=self._pr_number, login=contributor.login),
                RECREATED_MARKER,
                "## Problem",
                "",
                f"Contributed by @{contributor.login} in #{self._pr_number}, which cannot get the checks it needs because CI does not run fork code.",
                "",
                "## Changes",
                "",
                f"The fork pull request squashed at {approval.commit_sha}, the commit @{approval.login} approved.",
                "",
                "<details><summary>Original description</summary>",
                "",
                quoted,
                "",
                "</details>",
                "",
                *trailers,
            ]
        )

    def _hand_over(
        self, new_pr_number: int, approval: Approval, contributor: Contributor, fork_pr: Mapping[str, Any]
    ) -> bool:
        if self._enqueue:
            self._attempt("enqueue", lambda: self._add_merge_queue_label(new_pr_number))
        self._attempt(
            "request_review",
            lambda: self._github.request_pull_request_reviews(self._repository, new_pr_number, [approval.login]),
        )
        commented = self._attempt("comment", lambda: self._comment_once(new_pr_number, approval, contributor, fork_pr))
        if not commented:
            return False
        closed = self._attempt("close", lambda: self._github.close_pull_request(self._repository, self._pr_number))
        return bool(closed and closed.get("success"))

    def _attempt(self, step: str, call: Any) -> Any:
        try:
            return call()
        except (RecreationFailed, *_CALL_ERRORS):
            logger.warning(
                "fork_recreation_handover_step_failed", step=step, repository=self._repository, exc_info=True
            )
            return None

    def _add_merge_queue_label(self, new_pr_number: int) -> None:
        label = self._request(
            "GET", f"/repos/{self._repository}/labels/{MERGE_QUEUE_LABEL}", "/repos/{owner}/{repo}/labels/{name}"
        )
        if label.status_code == 200:
            self._github.add_pull_request_labels(self._repository, new_pr_number, [MERGE_QUEUE_LABEL])

    def _comment_once(
        self, new_pr_number: int, approval: Approval, contributor: Contributor, fork_pr: Mapping[str, Any]
    ) -> bool:
        already = self._app_commented()
        if already:
            return True
        if already is None:
            return False
        left_out = (
            f" Commits pushed after {approval.commit_sha[:7]} are not included."
            if fork_pr["head"]["sha"] != approval.commit_sha
            else ""
        )
        result = self._github.comment_on_pull_request(
            self._repository,
            self._pr_number,
            f"{RECREATED_MARKER}\nThank you @{contributor.login}! CI doesn't run code from forks, "
            f"so this change continues in #{new_pr_number}, with you as co-author.{left_out}",
        )
        return bool(result.get("success"))

    def _app_commented(self) -> bool | None:
        for page in range(1, MAX_COMMENT_PAGES + 1):
            response = self._request(
                "GET",
                f"/repos/{self._repository}/issues/{self._pr_number}/comments?per_page=100&page={page}",
                "/repos/{owner}/{repo}/issues/{issue_number}/comments",
            )
            if response.status_code != 200:
                return None
            comments = response.json()
            if any(
                RECREATED_MARKER in str(comment.get("body") or "")
                and matches_app_bot(comment.get("user"), self._app_login)
                for comment in comments
            ):
                return True
            if len(comments) < 100:
                return False
        return None

    def _delete_branch(self, branch: str) -> None:
        try:
            self._request(
                "DELETE", f"/repos/{self._repository}/git/refs/heads/{branch}", "/repos/{owner}/{repo}/git/refs/{ref}"
            )
        except RecreationFailed:
            logger.warning("fork_recreation_branch_cleanup_failed", repository=self._repository, branch=branch)

    def _graphql(self, fields: Sequence[str]) -> Mapping[str, Any]:
        query = (
            f"query {{ repository(owner: {_graphql_string(self._owner)}, name: {_graphql_string(self._name)}) "
            f"{{ {' '.join(fields)} }} }}"
        )
        data = self._post("/graphql", "/graphql", {"query": query}, expected=200)
        if data.get("errors") or not isinstance((data.get("data") or {}).get("repository"), dict):
            raise RecreationFailed("GitHub's GraphQL API returned errors")
        return data["data"]["repository"]

    def _get(self, path: str, endpoint: str) -> dict[str, Any]:
        response = self._request("GET", path, endpoint)
        if response.status_code != 200:
            raise RecreationFailed(f"GitHub answered {response.status_code} to GET {endpoint}")
        return response.json()

    def _post(self, path: str, endpoint: str, body: Mapping[str, Any], *, expected: int = 201) -> dict[str, Any]:
        response = self._request("POST", path, endpoint, body)
        if response.status_code != expected:
            raise RecreationFailed(f"GitHub answered {response.status_code} to POST {endpoint}")
        return response.json()

    def _request(
        self, method: str, path: str, endpoint: str, body: Mapping[str, Any] | None = None
    ) -> requests.Response:
        try:
            return self._github.api_request(method, path, endpoint=endpoint, json_body=body)
        except _CALL_ERRORS as error:
            raise RecreationFailed(f"GitHub did not answer {method} {endpoint}") from error


def recreate_fork_pull_request(
    *, team_id: int, installation_id: str, repository: str, pr_number: int, enqueue: bool = False
) -> ForkRecreationOutcome:
    rows = IntegrationManager.github.oauth.list_by_external_id(installation_id, team_ids=[team_id])
    if not rows:
        return ForkRecreationOutcome(
            created=False, message="PostHog Review can't reach this repository's GitHub installation."
        )
    github = GitHubIntegration(min(rows, key=lambda row: row.id), source=_SOURCE, priority=Priority.NORMAL)
    try:
        return ForkRecreation(github, repository, pr_number, app_login=posthog_app_login(), enqueue=enqueue).run()
    except RecreationRefused as refusal:
        return ForkRecreationOutcome(created=False, message=str(refusal))
    except RecreationFailed:
        logger.warning("fork_recreation_failed", repository=repository, pr_number=pr_number, exc_info=True)
        return ForkRecreationOutcome(
            created=False,
            message="GitHub refused a step of the re-creation, so no pull request was opened. Try again later.",
        )
