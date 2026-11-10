"""Admit a bot's PR to review when the repo policy names that bot.

`.stamphog/policy.yml` lists under `bot_authors` the bots whose PRs stamphog reviews. The list is
read from the repo's default branch only, so a PR cannot admit its own author. An admitted PR still
passes every gate, and the engine refuses it unless an attestation vouches for each file in it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.cache import cache

import yaml
import structlog

from posthog.dataclasses import frozen

from .github_client import StamphogGitHubClient

if TYPE_CHECKING:
    from ..models import StamphogRepoConfig

logger = structlog.get_logger(__name__)

POLICY_PATH = ".stamphog/policy.yml"
BOT_AUTHORS_CACHE_SECONDS = 300
_ADMITTING_ACTIONS = frozenset({"opened", "synchronize", "reopened"})


@frozen
class BotAuthor:
    name: str
    login: str
    id: int


def admitted_bot_author(repo_config: StamphogRepoConfig, pr: dict[str, Any], action: str) -> BotAuthor | None:
    """The policy entry that admits this PR, or None.

    The author must be a GitHub App account whose login and numeric id both match one entry, because
    a login can be renamed and claimed by someone else while the id cannot. The head must live in
    the repo itself, because the fork's owner controls a fork's branch. A transient policy fetch
    failure raises, so the caller retries the delivery rather than refusing a bot the policy admits.
    """
    if action not in _ADMITTING_ACTIONS:
        return None
    user = pr.get("user") or {}
    if user.get("type") != "Bot":
        return None
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or ""
    if head_repo.strip().lower() != repo_config.repository.strip().lower():
        return None
    login, user_id = user.get("login"), user.get("id")
    return next((bot for bot in load_repo_bot_authors(repo_config) if bot.login == login and bot.id == user_id), None)


def load_repo_bot_authors(repo_config: StamphogRepoConfig) -> tuple[BotAuthor, ...]:
    """The `bot_authors` entries on the repo's default branch, cached briefly, absence included."""
    key = f"stamphog:bot_authors:{repo_config.id}"
    cached = cache.get(key)
    if cached is None:
        raw_text = StamphogGitHubClient(repo_config.installation_id).get_default_branch_file(
            repo_config.repository, POLICY_PATH
        )
        cached = _parse_bot_authors(raw_text, repo_config.repository)
        cache.set(key, cached, BOT_AUTHORS_CACHE_SECONDS)
    return tuple(BotAuthor(**entry) for entry in cached)


def _parse_bot_authors(raw_text: str | None, repository: str) -> list[dict[str, Any]]:
    """Each well-formed entry as a plain mapping. A malformed entry admits nobody and is logged."""
    if raw_text is None:
        return []
    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        logger.warning("stamphog_bot_authors_invalid_yaml", repository=repository, exc_info=True)
        return []
    entries = parsed.get("bot_authors") if isinstance(parsed, dict) else None
    if not isinstance(entries, list):
        return []
    bot_authors: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not _is_identity(entry):
            logger.warning("stamphog_bot_author_entry_ignored", repository=repository)
            continue
        bot_authors.append({"name": entry["name"], "login": entry["login"], "id": entry["id"]})
    return bot_authors


def _is_identity(entry: dict[str, Any]) -> bool:
    user_id = entry.get("id")
    return (
        isinstance(entry.get("name"), str)
        and isinstance(entry.get("login"), str)
        and isinstance(user_id, int)
        and not isinstance(user_id, bool)
        and user_id > 0
    )
