"""GitHub data fetching via gh CLI + local git.

File stats come from the local checkout (git diff --numstat), everything
else (PR metadata, reviews, comments, check runs) from the GitHub API.
Also handles team membership checks for the ownership gate.
"""

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PRData:
    """All GitHub data needed to evaluate a PR."""

    number: int
    repo: str
    title: str
    state: str
    draft: bool
    mergeable_state: str
    author: str
    labels: list[str]
    base_sha: str
    head_sha: str
    files: list[dict]
    reviews: list[dict]
    review_comments: list[dict]
    check_runs: list[dict]
    base_ref: str = "master"
    author_is_bot: bool = False
    pr_reactions: list[dict] = field(default_factory=list)
    body: str = ""
    discussion: list[dict] = field(default_factory=list)

    @property
    def file_paths(self) -> list[str]:
        return [f["filename"] for f in self.files]

    @property
    def lines_added(self) -> int:
        return sum(f["additions"] for f in self.files)

    @property
    def lines_deleted(self) -> int:
        return sum(f["deletions"] for f in self.files)

    @property
    def lines_total(self) -> int:
        return self.lines_added + self.lines_deleted

    @property
    def has_new_files(self) -> bool:
        return any(f.get("status") == "A" for f in self.files)


_TRUSTED_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}

# Machine users that are real org members (type "User") but should still be
# treated as bots. GitHub Apps already report type "Bot" and aren't listed here.
_BOT_MACHINE_USERS = {"posthog-bot"}

# Bots whose reactions are deliberate review verdicts (👍 = reviewed clean,
# 👀 = review in flight). Other installed apps react for unrelated reasons
# (e.g. inkeep's 👎 is docs feedback), so bot reactions are allowlisted rather
# than trusted wholesale. GraphQL returns bot logins with the "[bot]" suffix.
TRUSTED_REACTOR_BOTS = {
    "chatgpt-codex-connector[bot]",
    "copilot-pull-request-reviewer[bot]",
    "greptile-apps[bot]",
    "hex-security-app[bot]",
    "veria-ai[bot]",
}


def is_bot_author(user: dict) -> bool:
    """True when the PR author is a bot or machine account.

    GitHub Apps (dependabot, mendral, other agents) report user.type == "Bot";
    machine users like posthog-bot are type "User", so match them by login.
    Mirrors the bot definition gating the jobs in pr-approval-agent.yml.
    """
    if user.get("type") == "Bot":
        return True
    login = (user.get("login") or "").lower()
    return "[bot]" in login or login in _BOT_MACHINE_USERS


# Stamphog's own review identities: REFUSE/ESCALATE comment reviews post via
# the GitHub App (stamphog[bot]); APPROVE reviews post via the workflow's
# GITHUB_TOKEN (github-actions[bot]) so they count toward branch protection.
_SELF_REVIEW_LOGINS = {"stamphog[bot]", "github-actions[bot]"}


def _prompt_worthy_author(login: str | None, association: str | None, is_bot: bool) -> bool:
    """One author-trust gate for reviews, inline comments, and discussion.

    Drops stamphog's own prior verdicts (they describe a stale snapshot the next
    run would misread as third-party tampering) and admits only trusted org
    members or bots. Without this, an untrusted external commenter could reach
    the prompt via discussion and grief it with a fake maintainer hold or forge
    a fake assurance claim. REST and GraphQL spell the author differently, so
    the caller passes the already-extracted login/association/bot-ness.
    """
    if login in _SELF_REVIEW_LOGINS:
        return False
    return is_bot or association == "BOT" or association in _TRUSTED_ASSOCIATIONS


def _normalize_reviews_for_prompt(reviews_raw: list[dict], head_sha: str) -> list[dict]:
    """Normalize top-level reviews for the reviewer prompt.

    Preserve trusted/bot reviews, and annotate whether each review was left on
    the current PR head. This lets the LLM distinguish active feedback from
    older context that may already have been addressed in follow-up commits.

    Stamphog's own prior reviews are excluded: they describe an earlier
    snapshot of the PR, are never independent review signal, and the reviewer
    has no way to recognize them as its own — re-reading a stale verdict after
    the PR state changed makes it suspect tampering and refuse forever.
    """
    normalized_reviews = []
    for review in reviews_raw:
        user = review.get("user") or {}
        if not _prompt_worthy_author(user.get("login"), review.get("author_association"), user.get("type") == "Bot"):
            continue

        commit_id = review.get("commit_id")
        normalized_reviews.append(
            {
                "user": review["user"]["login"],
                "state": review["state"],
                "body": review.get("body", ""),
                "commit_id": commit_id,
                "is_current_head": commit_id == head_sha,
                "submitted_at": review.get("submitted_at"),
            }
        )

    return normalized_reviews


def _normalize_discussion_for_prompt(comments_raw: list[dict]) -> list[dict]:
    """Normalize the PR's issue-comment timeline for the reviewer prompt.

    These are the general discussion comments (not inline review comments).
    Stamphog's own bot comments are excluded and the same author-trust gate as
    reviews/inline comments applies, so an untrusted external commenter can't
    slip a fake maintainer hold or assurance claim into the prompt.
    """
    normalized = []
    for comment in comments_raw:
        user = comment.get("user") or {}
        if not _prompt_worthy_author(user.get("login"), comment.get("author_association"), user.get("type") == "Bot"):
            continue
        normalized.append(
            {
                "user": user.get("login", "ghost"),
                "body": comment.get("body", ""),
                "created_at": comment.get("created_at"),
            }
        )
    return normalized


# GitHub spells reaction contents two ways: REST returns "+1"/"-1", GraphQL
# returns "THUMBS_UP"/"THUMBS_DOWN". Normalize both to an emoji so the reviewer
# sees a consistent signal regardless of which API surfaced the reaction.
_REACTION_EMOJI = {
    "+1": "👍",
    "thumbs_up": "👍",
    "-1": "👎",
    "thumbs_down": "👎",
    "laugh": "😄",
    "hooray": "🎉",
    "confused": "😕",
    "heart": "❤️",
    "rocket": "🚀",
    "eyes": "👀",
}


def _reaction_emoji(content: str) -> str:
    """Map a GitHub reaction content string (REST or GraphQL) to an emoji.

    Unknown values pass through unchanged so a newly-added reaction type still
    surfaces rather than silently disappearing.
    """
    return _REACTION_EMOJI.get(content.lower(), content)


def _is_org_member(org: str, login: str) -> bool:
    """Best-effort org-membership check; False on any error (fail closed)."""
    try:
        result = subprocess.run(
            ["gh", "api", f"orgs/{org}/members/{login}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _trusted_reactor_predicate(repo: str, author: str) -> Callable[[str], bool]:
    """Build a memoized `login -> bool` gate for whose reactions to trust.

    Reactions on a public PR can come from anyone, so only trust allowlisted
    reviewer bots and org members, and never the PR author (a self-reaction is
    not an independent signal). Unknown or erroring logins fail closed. Without
    this, any GitHub user could block auto-approval with an 👀 or fake an
    independent review with a 👍.
    """
    org = repo.split("/", 1)[0]
    cache: dict[str, bool] = {}

    def is_trusted(login: str) -> bool:
        if not login or login == "ghost" or login == author:
            return False
        if login not in cache:
            low = login.lower()
            if low.endswith("[bot]"):
                cache[login] = low in TRUSTED_REACTOR_BOTS
            else:
                cache[login] = _is_org_member(org, login)
        return cache[login]

    return is_trusted


def _normalize_reactions(node: dict, is_trusted: Callable[[str], bool]) -> list[dict]:
    """Normalize a GraphQL Reactable node's trusted reactions to [{user, emoji}].

    Works for any object that carries a `reactions` connection — the PR itself
    or an individual review comment. Reactions from untrusted actors (see
    `_trusted_reactor_predicate`) are dropped so they can't influence the verdict.
    """
    reactions = []
    for rn in (node.get("reactions") or {}).get("nodes") or []:
        login = (rn.get("user") or {}).get("login", "ghost")
        if is_trusted(login):
            reactions.append(
                {
                    "user": login,
                    "emoji": _reaction_emoji(rn.get("content", "")),
                    "created_at": rn.get("createdAt"),
                }
            )
    return reactions


def _gh_api(endpoint: str, *, paginate: bool = False) -> dict | list:
    cmd = ["gh", "api", endpoint]
    if paginate:
        # --paginate alone emits one JSON document per page, which json.loads
        # rejects on 2+ pages; --slurp wraps the pages in one outer array.
        cmd.extend(["--paginate", "--slurp"])
    else:
        sep = "&" if "?" in endpoint else "?"
        cmd[2] = f"{endpoint}{sep}per_page=100"
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {endpoint} failed: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    if paginate:
        flat: list = []
        for page in data:
            if isinstance(page, list):
                flat.extend(page)
            else:
                flat.append(page)
        return flat
    return data


# GitHub rejects GraphQL queries whose worst-case node count — the product of
# nested `first:` sizes — exceeds 500,000, before executing anything.
_REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $pr: Int!, $threadCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      reactions(first: 100) {
        nodes {
          content
          createdAt
          user { login }
        }
      }
      reviewThreads(first: 100, after: $threadCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          isOutdated
          path
          line
          comments(first: 50) {
            pageInfo { hasNextPage }
            nodes {
              author { login __typename }
              authorAssociation
              body
              databaseId
              replyTo { databaseId }
              reactions(first: 20) {
                nodes {
                  content
                  createdAt
                  user { login }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _gh_graphql(query: str, variables: dict | None = None) -> dict:
    """Run a GraphQL query via gh api graphql with proper variable passing."""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in (variables or {}).items():
        if value is None:
            cmd.extend(["-F", f"{key}=null"])
        elif isinstance(value, int):
            cmd.extend(["-F", f"{key}={value}"])
        else:
            cmd.extend(["-f", f"{key}={value}"])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"gh api graphql failed: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data


def _fetch_threads_and_reactions(repo: str, pr_number: int, author: str) -> tuple[list[dict], list[dict]]:
    """Fetch review-thread comments and reactions on the PR in one GraphQL call.

    Inline comments (each with their own reactions) and the reactions left on
    the PR itself come back from the same query, so no extra REST round trip is
    needed. Reactions are filtered to trusted, non-author actors. Returns
    (comments, pr_reactions); raises if any comment page is truncated.
    """
    owner, name = repo.split("/", 1)
    variables: dict = {"owner": owner, "name": name, "pr": pr_number, "threadCursor": None}
    is_trusted = _trusted_reactor_predicate(repo, author)

    comments: list[dict] = []
    pr_reactions: list[dict] = []
    while True:
        data = _gh_graphql(_REVIEW_THREADS_QUERY, variables)
        pull_request = data["data"]["repository"]["pullRequest"]
        # Reactions on the PR repeat on the pullRequest node on every page;
        # re-reading the (≤20) nodes each pass is trivial and avoids a flag.
        pr_reactions = _normalize_reactions(pull_request, is_trusted)
        review_threads = pull_request["reviewThreads"]
        threads = review_threads["nodes"]

        for thread in threads:
            comment_page = thread["comments"]
            if comment_page["pageInfo"]["hasNextPage"]:
                raise RuntimeError(
                    f"Review thread on {thread.get('path')}:{thread.get('line')} "
                    f"has >50 comments — pagination not implemented, escalate to human review"
                )
            for c in comment_page["nodes"]:
                # Same author-trust gate as reviews and discussion: stamphog's
                # own inline comments describe an earlier snapshot (feeding them
                # back reads as impersonation) and untrusted external commenters
                # are dropped. Reactions on these comments are also dropped — a
                # 👍 on stamphog's comment endorses stamphog's verdict, not the PR.
                comment_author = c.get("author") or {}
                if not _prompt_worthy_author(
                    comment_author.get("login"), c.get("authorAssociation"), comment_author.get("__typename") == "Bot"
                ):
                    continue
                reply_to = c.get("replyTo")
                comments.append(
                    {
                        "user": comment_author.get("login", "ghost"),
                        "body": c.get("body", ""),
                        "path": thread.get("path", ""),
                        "line": thread.get("line"),
                        "in_reply_to_id": reply_to["databaseId"] if reply_to else None,
                        "is_resolved": thread["isResolved"],
                        "is_outdated": thread["isOutdated"],
                        "reactions": _normalize_reactions(c, is_trusted),
                    }
                )

        page_info = review_threads["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        variables["threadCursor"] = page_info["endCursor"]

    return comments, pr_reactions


def _git_diff_files(base_sha: str, head_sha: str, repo_root: Path) -> list[dict]:
    """Get changed files with line counts and status from the local checkout."""
    diff_range = f"{base_sha}...{head_sha}"
    run_opts = {"capture_output": True, "text": True, "timeout": 30, "cwd": repo_root}

    numstat = subprocess.run(["git", "diff", "--numstat", diff_range], **run_opts)
    if numstat.returncode != 0:
        raise RuntimeError(f"git diff --numstat failed: {numstat.stderr.strip()}")

    name_status = subprocess.run(["git", "diff", "--name-status", diff_range], **run_opts)
    status_map: dict[str, str] = {}
    for line in name_status.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            status_map[parts[1]] = parts[0]

    files = []
    for line in numstat.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        added, deleted, filename = parts
        is_binary = added == "-"
        files.append(
            {
                "filename": filename,
                "additions": int(added) if not is_binary else 0,
                "deletions": int(deleted) if not is_binary else 0,
                "binary": is_binary,
                "status": status_map.get(filename, "M"),
            }
        )
    return files


def write_pr_diff(base_sha: str, head_sha: str, dest: Path, repo_root: Path) -> Path:
    """Write the base...head PR diff to `dest` from the local checkout.

    Shared by the reviewer (feeds the LLM the diff to read) and the familiarity
    signal (parses the same diff for base-side modified line ranges), so the
    `git diff` invocation lives in one place.
    """
    result = subprocess.run(
        ["git", "diff", f"{base_sha}...{head_sha}"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=repo_root,
    )
    dest.write_text(result.stdout if result.returncode == 0 else f"git diff failed: {result.stderr}")
    return dest


def _have_commit(sha: str, repo_root: Path) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-t", sha],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        ).returncode
        == 0
    )


def ensure_commits(pr_number: int, head_sha: str, base_ref: str, base_sha: str, repo_root: Path) -> None:
    """Make the PR head and its base commit available locally.

    The workflow checks out master and fetches `pull/<n>/head`, which covers
    the common case. Two stacked-PR cases need more:
      - The head: fetched explicitly if the merge commit isn't present.
      - The base: a stacked PR targets its parent branch, not master, so
        `base_sha` is the parent's tip. It's usually an ancestor of the head
        (reachable once the head is fetched), but a rebased/force-pushed stack
        can leave it unreachable — fetch the base branch by name to be sure.
        `git diff base_sha...head_sha` (and dismiss_check's ancestry walk)
        need that object present. Best-effort: a missing base surfaces later
        as a diff error rather than a silent wrong scope.
    """
    if not _have_commit(head_sha, repo_root):
        subprocess.run(
            ["git", "fetch", "--filter=blob:none", "origin", f"pull/{pr_number}/head"],
            cwd=repo_root,
            capture_output=True,
            timeout=60,
        )
    if not _have_commit(base_sha, repo_root):
        subprocess.run(
            ["git", "fetch", "--filter=blob:none", "origin", base_ref],
            cwd=repo_root,
            capture_output=True,
            timeout=60,
        )


def fetch_pr(pr_number: int, repo: str, repo_root: Path | None = None) -> PRData:
    """Fetch PR data: metadata from API, file stats from local git."""
    pr = _gh_api(f"repos/{repo}/pulls/{pr_number}")
    reviews_raw = _gh_api(f"repos/{repo}/pulls/{pr_number}/reviews", paginate=True)

    # Discussion is advisory context only. Skip it for bot PRs (refused before
    # any prompt is built) and never let a transient gh failure fail the run —
    # an exception here would turn the wait-loop refetch into a spurious WAIT.
    author_is_bot = is_bot_author(pr.get("user", {}))
    discussion: list[dict] = []
    if not author_is_bot:
        try:
            discussion_raw = _gh_api(f"repos/{repo}/issues/{pr_number}/comments", paginate=True)
            discussion = _normalize_discussion_for_prompt(discussion_raw)
        except Exception as exc:
            print(f"warning: discussion fetch failed ({exc}); continuing with no discussion context")  # noqa: T201

    base_ref = pr["base"]["ref"]
    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]
    check_runs_resp = _gh_api(f"repos/{repo}/commits/{head_sha}/check-runs")

    git_root = repo_root or Path.cwd()
    ensure_commits(pr_number, head_sha, base_ref, base_sha, git_root)
    files = _git_diff_files(base_sha, head_sha, git_root)

    review_comments, pr_reactions = _fetch_threads_and_reactions(repo, pr_number, pr["user"]["login"])

    return PRData(
        number=pr_number,
        repo=repo,
        title=pr["title"],
        state=pr["state"],
        draft=pr.get("draft", False),
        mergeable_state=pr.get("mergeable_state", "unknown"),
        author=pr["user"]["login"],
        labels=[label["name"] for label in pr.get("labels", [])],
        base_ref=base_ref,
        base_sha=base_sha,
        head_sha=head_sha,
        files=files,
        reviews=_normalize_reviews_for_prompt(reviews_raw, head_sha),
        review_comments=review_comments,
        check_runs=check_runs_resp.get("check_runs", []),
        author_is_bot=author_is_bot,
        pr_reactions=pr_reactions,
        body=pr.get("body") or "",
        discussion=discussion,
    )


def check_team_membership(author: str, team_slug: str) -> bool:
    """Check if author is an active member of the given GitHub team."""
    try:
        result = subprocess.run(
            ["gh", "api", f"orgs/PostHog/teams/{team_slug}/memberships/{author}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout).get("state") == "active"
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return False
