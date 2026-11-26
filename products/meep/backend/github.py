import re
from typing import Any
from urllib.parse import urlsplit

from rest_framework.exceptions import ValidationError

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationError, ReauthorizationRequired
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

REPOSITORY = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
URL = re.compile(r"https?://[^\s<>\[\]()]+", re.IGNORECASE)


def mission_repository(text: str) -> str | None:
    repositories = set()
    for match in URL.finditer(text):
        try:
            url = urlsplit(match[0].rstrip(".,;:!?"))
        except ValueError:
            continue
        if url.netloc.lower() != "github.com":
            continue
        parts = url.path.strip("/").split("/")
        if len(parts) == 2 or (len(parts) == 4 and parts[2] in {"issues", "pull"} and parts[3].isdigit()):
            name = "/".join(parts[:2]).removesuffix(".git").lower()
            if REPOSITORY.fullmatch(name) and name.split("/")[1] not in {".", ".."}:
                repositories.add(name)
    return repositories.pop() if len(repositories) == 1 else None


def selected_repository(state: dict[str, Any]) -> str | None:
    names = [
        watch["key"]
        for watch in state.get("topic", {}).get("context_sources", [])
        if watch["connection"] == "github" and watch["kind"] == "repository"
    ]
    if len(names) > 1:
        raise ValidationError("Choose one GitHub repository for this topic.")
    if names and (not REPOSITORY.fullmatch(names[0]) or names[0].split("/")[1] in {".", ".."}):
        raise ValidationError("Choose a valid GitHub repository.")
    return names[0] if names else None


def repository_catalog(owner_id: int) -> dict[str, Any]:
    names: set[str] = set()
    connected = False
    unavailable = False
    for row in UserIntegration.objects.filter(user_id=owner_id, kind="github"):
        github = UserGitHubIntegration(row, source="meep_topic_context", priority=Priority.NORMAL)
        if (
            github.needs_reauthorization
            or github.installation_unavailable()
            or github.user_refresh_token_expired()
            or not github.user_access_token
        ):
            continue
        try:
            repositories = github.list_all_cached_repositories()
        except ReauthorizationRequired:
            continue
        except (GitHubIntegrationError, GitHubRateLimitError):
            unavailable = True
            continue
        connected = True
        names.update(repo["full_name"] for repo in repositories if repo.get("full_name"))
    return {"connected": connected or unavailable, "unavailable": unavailable, "repositories": sorted(names)}


GITHUB_INSTRUCTIONS = (
    "When GitHub context would help, read the current account and repositories with meep-topic-get. Connections can change between turns. "
    "If several match, ask which one. To inspect a repository, start a board task using meep-task-start "
    "with exactly one canonical https://github.com/owner/repo URL in its brief and wait for its findings. "
    "Use the saved repository when it fits the question. Reading does not save a link. "
    "If saving or replacing a repository would help future questions, explain why in reply and return its "
    "full name in suggested_repository. Otherwise return null. The person approves the change in Meep."
)


def repository_suggestion(candidate: object, state: dict) -> str | dict:
    if not isinstance(candidate, str) or not REPOSITORY.fullmatch(candidate) or candidate.split("/")[1] in {".", ".."}:
        return "Handled"
    current = next(
        (
            w
            for w in state["topic"].get("context_sources", [])
            if w["connection"] == "github" and w["kind"] == "repository"
        ),
        None,
    )
    if current and current["key"].lower() == candidate.lower():
        return "Handled"
    reason = f"Replace {current['key']} with {candidate}?" if current else f"Link {candidate} to this topic?"
    return {
        "NeedsYou": {
            "reason": reason,
            "suggestions": [
                {"LinkRepository": {"repository": candidate, "previous": current["id"] if current else None}},
                "Leave",
            ],
        }
    }
