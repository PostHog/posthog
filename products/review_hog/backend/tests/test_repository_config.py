import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration.github import GitHubIntegration

from products.review_hog.backend.repository_config import (
    REPOSITORY_CONFIG_PATH,
    RepositoryConfigError,
    RepositoryReviewConfig,
    load_repository_config,
    parse_repository_config,
)

_EVENT: dict = {"action": "opened", "draft": False, "base_ref": "master", "labels": (), "author_login": "octocat"}


class TestParseRepositoryConfig(SimpleTestCase):
    def test_empty_file_means_every_default(self) -> None:
        config = parse_repository_config("")

        assert config == RepositoryReviewConfig()
        assert config.author_opt_in_required is True
        assert config.flash_reasoning_effort is None
        assert config.skip_reason(**_EVENT) is None

    def test_a_key_with_no_value_means_its_default(self) -> None:
        config = parse_repository_config("base_branches:\nskip_labels:\nignore_authors:\nflash:\ninstructions:\n")

        assert config == RepositoryReviewConfig()

    def test_every_option_is_read(self) -> None:
        config = parse_repository_config(
            "enabled: true\nauthors: members\ndrafts: false\npushes: false\nbase_branches: ['release/*']\n"
            "skip_labels: ['no-review']\nignore_authors: ['*[bot]']\nflash:\n  effort: xhigh\n"
            "instructions: |\n  Flag blocking calls in async code.\n"
        )

        assert config.author_opt_in_required is False
        assert config.flash_reasoning_effort == "xhigh"
        assert config.instructions == "Flag blocking calls in async code.\n"
        assert config.skip_reason(**{**_EVENT, "base_ref": "release/2026.10"}) is None

    @parameterized.expand(
        [
            ("not_yaml", "enabled: [unclosed"),
            ("not_a_mapping", "- enabled"),
            ("unknown_key", "enable: true"),
            ("unknown_authors_policy", "authors: everyone"),
            ("unknown_effort", "flash:\n  effort: low"),
            ("instructions_too_long", "instructions: " + "x" * 4_001),
        ]
    )
    def test_invalid_files_are_rejected(self, _name: str, text: str) -> None:
        with pytest.raises(RepositoryConfigError, match=REPOSITORY_CONFIG_PATH):
            parse_repository_config(text)

    @parameterized.expand(
        [
            ("disabled", "enabled: false", {}, "config_disabled"),
            ("draft", "drafts: false", {"draft": True}, "draft_skipped"),
            ("draft_allowed_by_default", "", {"draft": True}, None),
            ("push", "pushes: false", {"action": "synchronize"}, "push_skipped"),
            ("ready_after_draft_reviews", "", {"action": "ready_for_review"}, "ready_for_review_skipped"),
            ("ready_starts_the_first_review", "drafts: false", {"action": "ready_for_review"}, None),
            ("base_branch", "base_branches: ['main', 'release/*']", {"base_ref": "master"}, "base_branch_skipped"),
            ("base_branch_glob", "base_branches: ['main', 'release/*']", {"base_ref": "release/1"}, None),
            ("default_skip_label", "", {"labels": ("no-reviewhog",)}, "label_skipped"),
            ("custom_skip_label", "skip_labels: ['chore']", {"labels": ("no-reviewhog", "chore")}, "label_skipped"),
            ("custom_skip_label_replaces_default", "skip_labels: ['chore']", {"labels": ("no-reviewhog",)}, None),
            ("skip_label_ignores_case", "", {"labels": ("No-ReviewHog",)}, "label_skipped"),
            (
                "ignored_author_glob",
                "ignore_authors: ['*[bot]']",
                {"author_login": "dependabot[bot]"},
                "author_ignored",
            ),
            ("ignored_author_case", "ignore_authors: ['OctoCat']", {"author_login": "octocat"}, "author_ignored"),
            ("disabled_wins_over_everything", "enabled: false\ndrafts: false", {"draft": True}, "config_disabled"),
        ]
    )
    def test_skip_reason(self, _name: str, text: str, event: dict, expected: str | None) -> None:
        assert parse_repository_config(text).skip_reason(**{**_EVENT, **event}) == expected


class TestLoadRepositoryConfig(SimpleTestCase):
    def _integration(self) -> MagicMock:
        integration = MagicMock()
        integration.kind = "github"
        return integration

    @parameterized.expand(
        [
            ("present", {"sha": "s", "size": 14, "content": "enabled: false"}, False),
            ("absent", None, None),
        ]
    )
    @patch.object(GitHubIntegration, "get_file_entry")
    def test_reads_the_file_at_the_requested_ref(
        self, _name: str, entry: dict | None, expected_enabled: bool | None, get_file_entry: MagicMock
    ) -> None:
        get_file_entry.return_value = entry

        config = load_repository_config(self._integration(), "PostHog/posthog-js", "abc123")

        get_file_entry.assert_called_once_with("PostHog/posthog-js", REPOSITORY_CONFIG_PATH, ref="abc123")
        assert (config.enabled if config is not None else None) == expected_enabled

    @patch.object(GitHubIntegration, "get_file_entry", return_value={"sha": "s", "size": 2_000_000, "content": None})
    def test_oversized_file_is_invalid(self, _get_file_entry: MagicMock) -> None:
        with pytest.raises(RepositoryConfigError, match="too large"):
            load_repository_config(self._integration(), "PostHog/posthog", "abc123")
