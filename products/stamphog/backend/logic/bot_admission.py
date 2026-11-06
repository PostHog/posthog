"""Which bot-authored PRs a repository's `bot_authors` policy admits, from facts GitHub attests.

The engine enforces the admission's condition, that CI attests every changed file.
"""

from typing import Any

from posthog.dataclasses import frozen

from .repo_policy import policy_list

# GitHub commits and signs as this user for a commit it creates on an App's behalf through the API.
WEB_FLOW_LOGIN = "web-flow"


@frozen
class BotAuthorRule:
    login: str
    id: int
    branch_prefix: str


def bot_author_rules(policy_text: str | None) -> list[BotAuthorRule]:
    """The bots a repository's default-branch policy admits. The engine validates the entries."""
    return [
        BotAuthorRule(login=entry["login"], id=entry["id"], branch_prefix=entry["branch_prefix"])
        for entry in policy_list(policy_text, "bot_authors")
        if isinstance(entry.get("login"), str)
        and isinstance(entry.get("id"), int)
        and isinstance(entry.get("branch_prefix"), str)
        and entry["branch_prefix"]
    ]


def matching_rule(rules: list[BotAuthorRule], pr: dict[str, Any], repo: str) -> BotAuthorRule | None:
    """The rule for this PR's author, when the bot opened it on a same-repository branch under its prefix."""
    user = pr.get("user") or {}
    head = pr.get("head") or {}
    if str((head.get("repo") or {}).get("full_name") or "").lower() != repo.lower():
        return None
    return next(
        (
            rule
            for rule in rules
            if user.get("login") == rule.login
            and user.get("id") == rule.id
            and str(head.get("ref") or "").startswith(rule.branch_prefix)
        ),
        None,
    )


def commits_are_the_bots_own(commits: list[dict], rule: BotAuthorRule) -> bool:
    """True when GitHub verified every commit as made for the bot.

    A person can set any author on a commit they push, but GitHub verifies a signature only against
    the committer: `web-flow` for a commit GitHub created itself, or the bot for one the bot signed.
    A bot account holds no key a person could sign with.
    """
    return bool(commits) and all(
        (commit.get("author") or {}).get("id") == rule.id
        and (
            (commit.get("committer") or {}).get("login") == WEB_FLOW_LOGIN
            or (commit.get("committer") or {}).get("id") == rule.id
        )
        and ((commit.get("commit") or {}).get("verification") or {}).get("verified") is True
        for commit in commits
    )
