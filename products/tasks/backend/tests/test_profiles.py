from contextlib import nullcontext
from dataclasses import replace

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.profiles import (
    GithubAccess,
    GithubResolution,
    Read,
    SourceKind,
    TaskProfile,
    TaskProfileError,
    TaskSource,
    TaskSourceError,
    check_task_source,
    get_task_profile,
    public_profile_for_origin,
    register_task_profile,
    resolve_task_origin,
)

BUSINESS_KNOWLEDGE = get_task_profile("business_knowledge")
REPORT_PROFILE = replace(BUSINESS_KNOWLEDGE, key="test.report", source_kind=SourceKind.SIGNAL_REPORT)
REPORT_SOURCE = TaskSource(kind=SourceKind.SIGNAL_REPORT, id="report-1")
FLOW_SOURCE = TaskSource(kind=SourceKind.HOG_FLOW, id="5ab01f4d-5b1e-4990-9802-4f8792a76759")


class TestTaskProfileRegistry(SimpleTestCase):
    @parameterized.expand(
        [
            ("read_without_channel", {"read_without_channel": Read.TEAM}),
            ("idle_minutes", {"idle_minutes": 5}),
            ("too_many_hidden_mcp_tools", {"mcp_exclude_tools": tuple(f"tool-{i}" for i in range(33))}),
        ]
    )
    def test_rejects_an_invalid_profile(self, _name: str, overrides: dict) -> None:
        conflicting = replace(BUSINESS_KNOWLEDGE, key="test.conflicting", **overrides)

        with self.assertRaises(TaskProfileError):
            register_task_profile(conflicting)

    @parameterized.expand(
        [
            ("always_with_write", GithubResolution.ALWAYS, GithubAccess.WRITE, False),
            ("always_with_read", GithubResolution.ALWAYS, GithubAccess.READ, False),
            ("with_repository_with_write", GithubResolution.WITH_REPOSITORY, GithubAccess.WRITE, False),
            ("never_with_none", GithubResolution.NEVER, GithubAccess.NONE, False),
            ("always_with_none", GithubResolution.ALWAYS, GithubAccess.NONE, True),
            ("with_repository_with_none", GithubResolution.WITH_REPOSITORY, GithubAccess.NONE, True),
            ("never_with_read", GithubResolution.NEVER, GithubAccess.READ, True),
            ("never_with_write", GithubResolution.NEVER, GithubAccess.WRITE, True),
        ]
    )
    def test_register_requires_github_access_to_agree_with_github_resolution(
        self, _name: str, resolution: GithubResolution, access: GithubAccess, refused: bool
    ) -> None:
        candidate = replace(
            BUSINESS_KNOWLEDGE, key="test.github_pair", github_resolution=resolution, github_access=access
        )

        with (
            patch.dict("products.tasks.backend.facade.profiles._profiles"),
            self.assertRaises(TaskProfileError) if refused else nullcontext(),
        ):
            register_task_profile(candidate)

            self.assertEqual(get_task_profile("test.github_pair"), candidate)

    @parameterized.expand(
        [
            ("unlisted", BUSINESS_KNOWLEDGE, ("business_knowledge", True, "business_knowledge")),
            ("listed", get_task_profile("user"), ("user_created", False, "user")),
        ]
    )
    def test_resolve_task_origin_follows_the_profile(
        self, _name: str, profile: TaskProfile, expected: tuple[str, bool, str]
    ) -> None:
        resolved = resolve_task_origin(profile)

        self.assertEqual((resolved.origin_product, resolved.internal, resolved.profile_key), expected)

    @parameterized.expand(
        [
            ("origin_with_a_public_profile", "user_created", "user"),
            ("origin_with_an_inbox_profile", "signal_report", "signals.inbox"),
            ("origin_with_a_private_profile", "business_knowledge", None),
            ("origin_with_no_profile", "knowledge_writer", None),
        ]
    )
    def test_public_profile_for_origin(self, _name: str, origin: str, expected_key: str | None) -> None:
        profile = public_profile_for_origin(origin)

        self.assertEqual(profile.key if profile else None, expected_key)

    def test_register_refuses_a_second_public_profile_on_an_origin(self) -> None:
        second = replace(get_task_profile("user"), key="test.second_public_user")

        with patch.dict("products.tasks.backend.facade.profiles._profiles"), self.assertRaises(TaskProfileError):
            register_task_profile(second)

    @parameterized.expand(
        [
            ("profile_without_kind_or_source", BUSINESS_KNOWLEDGE, None, False),
            ("profile_with_matching_source", REPORT_PROFILE, REPORT_SOURCE, False),
            ("profile_without_kind_given_source", BUSINESS_KNOWLEDGE, REPORT_SOURCE, True),
            ("profile_with_kind_missing_source", REPORT_PROFILE, None, True),
            ("profile_with_kind_other_source", REPORT_PROFILE, FLOW_SOURCE, True),
        ]
    )
    def test_check_task_source_matches_the_profile(
        self, _name: str, profile: TaskProfile, source: TaskSource | None, refused: bool
    ) -> None:
        with self.assertRaises(TaskSourceError) if refused else nullcontext():
            check_task_source(profile=profile, source=source)
