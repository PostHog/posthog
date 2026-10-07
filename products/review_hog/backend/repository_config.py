"""The per-repository file that turns automatic Flash reviews on and tunes them.

A repository opts into automatic reviews by committing `.github/review-hog.yml`. The automatic
trigger reads it from the repository's default branch, never from the pull request's head: the file
decides who is reviewed and adds guidance to the reviewer's prompt, so the author of the pull request
under review must not be able to change it for that review. The file is small on purpose: it decides
whether a pull request is reviewed and with what budget; the review perspectives, validator, and
severity threshold stay with the acting user's PostHog Review settings.
"""

import re
import fnmatch
from collections.abc import Sequence
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import Integration
from posthog.models.integration.github import GitHubIntegration

REPOSITORY_CONFIG_PATH = ".github/review-hog.yml"

AuthorsPolicy = Literal["opted_in", "members"]
# The values of `ReviewUserSettings.FlashReasoningEffort`, so a config effort can replace a user's.
FlashEffort = Literal["medium", "xhigh"]
SkipReason = Literal[
    "config_disabled",
    "draft_skipped",
    "push_skipped",
    "base_branch_skipped",
    "label_skipped",
    "author_ignored",
]

MAX_INSTRUCTIONS_CHARS = 4_000


def _login_matches(login: str, pattern: str) -> bool:
    # Bot logins end in "[bot]", which fnmatch would read as a character class, so brackets are
    # literal here: only "*" and "?" are wildcards in an `ignore_authors` pattern.
    return fnmatch.fnmatchcase(login.lower(), re.sub(r"[\[\]]", r"[\g<0>]", pattern.lower()))


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
    # A pull request carrying any of these labels is not reviewed. GitHub label names are unique
    # without regard to case, so the comparison ignores case too.
    skip_labels: list[str] = Field(default_factory=lambda: ["no-reviewhog"])
    # Patterns against the author's GitHub login, compared case-insensitively; "*" and "?" are
    # wildcards and brackets are literal, so "*[bot]" matches every GitHub App bot.
    ignore_authors: list[str] = Field(default_factory=list)
    flash: FlashConfig = Field(default_factory=FlashConfig)
    # Repository-wide guidance added to every review perspective's prompt.
    instructions: str = Field(default="", max_length=MAX_INSTRUCTIONS_CHARS)

    @field_validator("*", mode="before")
    @classmethod
    def _empty_value_means_default(cls, value: object, info: ValidationInfo) -> object:
        # YAML reads a key with no value (`ignore_authors:`) as null. That is the key's default,
        # not an invalid file that stops every review in the repository.
        if value is not None or info.field_name is None:
            return value
        return cls.model_fields[info.field_name].get_default(call_default_factory=True)

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
        # `ready_for_review` passes even when drafts are reviewed: the draft's own events may have
        # been skipped by a label or a missing opt-in that has since cleared. The automatic turn
        # stops on a head it already completed, so a draft that was reviewed is not reviewed twice.
        if not any(fnmatch.fnmatchcase(base_ref, pattern) for pattern in self.base_branches):
            return "base_branch_skipped"
        skip_labels = {label.lower() for label in self.skip_labels}
        if any(label.lower() in skip_labels for label in labels):
            return "label_skipped"
        if any(_login_matches(author_login, pattern) for pattern in self.ignore_authors):
            return "author_ignored"
        return None


class _UniqueKeySafeLoader(yaml.SafeLoader):
    # PyYAML keeps the last of two equal keys, so `enabled: false` followed by `enabled: true`
    # would load as a valid file that silently applies only one of the two values.
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen: set[object] = set()
        for key_node, _ in node.value:
            # A `<<` merge key has no constructor of its own, and an explicit key may override a
            # merged one, so only the explicit keys are checked. The parent expands the merge.
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError:
                continue
            if duplicate:
                raise yaml.constructor.ConstructorError(None, None, "duplicate key", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _yaml_error_summary(error: yaml.YAMLError) -> str:
    # The str() of a marked YAML error quotes the offending source line, and a malformed file can
    # hold a token. The summary keeps only the problem and its position, so the log stays safe.
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark is not None:
        mark = error.problem_mark
        return f"{error.problem} at line {mark.line + 1}, column {mark.column + 1}"
    return type(error).__name__


def _validation_error_summary(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in detail['loc']) or 'file'}: {detail['msg']}"
        for detail in error.errors(include_input=False, include_url=False)
    )


def parse_repository_config(text: str) -> RepositoryReviewConfig:
    loader = _UniqueKeySafeLoader(text)
    try:
        # A file with no document (empty, or comments only) has no node and means every default.
        # An explicit `null` document has a node, so it reaches the mapping check and is rejected.
        node = loader.get_single_node()
        raw = {} if node is None else loader.construct_document(node)
    except yaml.YAMLError as e:
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} is not valid YAML: {_yaml_error_summary(e)}") from e
    finally:
        loader.dispose()
    if not isinstance(raw, dict):
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} must be a mapping at the top level")
    try:
        return RepositoryReviewConfig.model_validate(raw)
    except ValidationError as e:
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} is invalid: {_validation_error_summary(e)}") from e


def load_repository_config(integration: Integration, repository: str) -> RepositoryReviewConfig | None:
    """The repository's config on its default branch, None when the file does not exist.

    Raises `RepositoryConfigError` for a file that exists but cannot be used, and lets GitHub
    transport errors propagate so the caller's retry policy decides.
    """
    # NORMAL, not the integration's CRITICAL default: nobody blocks on an automatic review, so the
    # read must not spend the reserve kept for interactive traffic on the shared installation budget.
    github = GitHubIntegration(integration, source="review_hog", priority=Priority.NORMAL)
    try:
        # No ref, so GitHub reads the default branch, which the pull request's author cannot change.
        entry = github.get_file_entry(repository, REPOSITORY_CONFIG_PATH)
    except UnicodeDecodeError as e:
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} is not UTF-8 text") from e
    if entry is None:
        return None
    content = entry["content"]
    if content is None:
        raise RepositoryConfigError(f"{REPOSITORY_CONFIG_PATH} is too large to read inline")
    return parse_repository_config(content)
