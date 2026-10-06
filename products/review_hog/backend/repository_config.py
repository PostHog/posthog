"""The per-repository file that turns automatic Flash reviews on and tunes them.

A repository opts into automatic reviews by committing `.github/review-hog.yml`. The automatic
trigger reads it from the pull request's head commit, so a change to the file can be tried on its
own pull request before it lands. The file is small on purpose: it decides whether a pull request is
reviewed and with what budget; the review perspectives, validator, and severity threshold stay with
the acting user's PostHog Review settings.
"""

import re
import fnmatch
from collections.abc import Sequence
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import Integration
from posthog.models.integration.github import GitHubIntegration

REPOSITORY_CONFIG_PATH = ".github/review-hog.yml"

AuthorsPolicy = Literal["opted_in", "members"]
# The values of `ReviewUserSettings.FlashReasoningEffort`, so a config effort can replace a user's.
FlashEffort = Literal["medium", "xhigh"]
SkipReason = Literal[
    "config_disabled", "draft_skipped", "push_skipped", "base_branch_skipped", "label_skipped", "author_ignored"
]

MAX_INSTRUCTIONS_CHARS = 4_000


def _login_matches(login: str, pattern: str) -> bool:
    # Bot logins end in "[bot]", which fnmatch would read as a character class, so brackets are
    # literal here: only "*" and "?" are wildcards in an `ignore_authors` pattern.
    literal_brackets = re.sub(r"[\[\]]", lambda match: "[[]" if match.group() == "[" else "[]]", pattern.lower())
    return fnmatch.fnmatchcase(login.lower(), literal_brackets)


class RepositoryConfigError(ValueError):
    """The file exists but cannot drive a review: not YAML, not a mapping, or an invalid field."""


class FlashConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None means each author's own Flash strength setting applies.
    effort: FlashEffort | None = None


class RepositoryReviewConfig(BaseModel):
    """`.github/review-hog.yml`, validated. Unknown keys are rejected so a typo cannot silently
    disable the option it meant to set."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # `opted_in`: only authors who turned on "Review all your PRs in Flash mode". `members`: every
    # author who maps to a PostHog user on the reviewing team, no per-user opt-in needed.
    authors: AuthorsPolicy = "opted_in"
    drafts: bool = True
    # Whether a push to an open pull request starts a new review, or only the opening does.
    pushes: bool = True
    # fnmatch patterns against the pull request's base branch name.
    base_branches: list[str] = Field(default_factory=lambda: ["*"])
    # A pull request carrying any of these labels is not reviewed.
    skip_labels: list[str] = Field(default_factory=lambda: ["no-reviewhog"])
    # Patterns against the author's GitHub login, compared case-insensitively; "*" and "?" are
    # wildcards and brackets are literal, so "*[bot]" matches every GitHub App bot.
    ignore_authors: list[str] = Field(default_factory=list)
    flash: FlashConfig = Field(default_factory=FlashConfig)
    # Repository-wide guidance added to every review perspective's prompt.
    instructions: str = Field(default="", max_length=MAX_INSTRUCTIONS_CHARS)

    @property
    def author_opt_in_required(self) -> bool:
        return self.authors == "opted_in"

    @property
    def flash_reasoning_effort(self) -> FlashEffort | None:
        return self.flash.effort

    def skip_reason(
        self, *, action: str, draft: bool, base_ref: str, labels: Sequence[str], author_login: str
    ) -> SkipReason | None:
        """Why this pull request event is not reviewed under this config, or None when it is."""
        if not self.enabled:
            return "config_disabled"
        if draft and not self.drafts:
            return "draft_skipped"
        if action == "synchronize" and not self.pushes:
            return "push_skipped"
        if not any(fnmatch.fnmatchcase(base_ref, pattern) for pattern in self.base_branches):
            return "base_branch_skipped"
        if any(label in self.skip_labels for label in labels):
            return "label_skipped"
        if any(_login_matches(author_login, pattern) for pattern in self.ignore_authors):
            return "author_ignored"
        return None


def parse_repository_config(text: str) -> RepositoryReviewConfig:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} is not valid YAML: {e}") from e
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} must be a mapping at the top level")
    try:
        return RepositoryReviewConfig.model_validate(raw)
    except ValidationError as e:
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} is invalid: {e}") from e


def load_repository_config(integration: Integration, repository: str, ref: str) -> RepositoryReviewConfig | None:
    """The repository's config at `ref`, None when the file does not exist.

    Raises `RepositoryConfigError` for a file that exists but cannot be used, and lets GitHub
    transport errors propagate so the caller's retry policy decides.
    """
    # NORMAL, not the integration's CRITICAL default: nobody blocks on an automatic review, so the
    # read must not spend the reserve kept for interactive traffic on the shared installation budget.
    github = GitHubIntegration(integration, source="review_hog", priority=Priority.NORMAL)
    entry = github.get_file_entry(repository, REPOSITORY_CONFIG_PATH, ref=ref)
    if entry is None:
        return None
    content = entry["content"]
    if content is None:
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} is too large to read inline")
    return parse_repository_config(content)
