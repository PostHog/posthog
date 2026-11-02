from contextlib import nullcontext
from dataclasses import replace

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.profiles import (
    Read,
    SourceKind,
    TaskProfile,
    TaskProfileError,
    TaskSource,
    TaskSourceError,
    check_task_source,
    get_task_profile,
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
        ]
    )
    def test_rejects_a_profile_that_disagrees_with_its_origin(self, _name: str, overrides: dict) -> None:
        conflicting = replace(BUSINESS_KNOWLEDGE, key="test.conflicting", **overrides)

        with self.assertRaises(TaskProfileError):
            register_task_profile(conflicting)

    @parameterized.expand(
        [
            ("profile_only", BUSINESS_KNOWLEDGE, None, None, ("business_knowledge", True, "business_knowledge")),
            (
                "profile_and_matching_origin",
                BUSINESS_KNOWLEDGE,
                "business_knowledge",
                None,
                ("business_knowledge", True, "business_knowledge"),
            ),
            (
                "profile_and_matching_internal",
                BUSINESS_KNOWLEDGE,
                None,
                True,
                ("business_knowledge", True, "business_knowledge"),
            ),
            ("origin_and_internal", None, "business_knowledge", True, ("business_knowledge", True, None)),
            ("origin_without_internal", None, "user_created", None, ("user_created", False, None)),
        ]
    )
    def test_resolve_task_origin_accepts_a_profile_or_an_origin(
        self,
        _name: str,
        profile: TaskProfile | None,
        origin: str | None,
        internal: bool | None,
        expected: tuple[str, bool, str | None],
    ) -> None:
        resolved = resolve_task_origin(profile=profile, origin_product=origin, internal=internal)

        self.assertEqual((resolved.origin_product, resolved.internal, resolved.profile_key), expected)

    @parameterized.expand(
        [
            ("neither", None, None, None),
            ("empty_origin", None, "", None),
            ("internal_without_origin", None, None, True),
            ("origin_mismatch", BUSINESS_KNOWLEDGE, "loop", None),
            ("internal_mismatch", BUSINESS_KNOWLEDGE, None, False),
        ]
    )
    def test_resolve_task_origin_rejects_conflicting_input(
        self, _name: str, profile: TaskProfile | None, origin: str | None, internal: bool | None
    ) -> None:
        with self.assertRaises(TaskProfileError):
            resolve_task_origin(profile=profile, origin_product=origin, internal=internal)

    @parameterized.expand(
        [
            ("no_profile_with_source", None, FLOW_SOURCE, False),
            ("no_profile_without_source", None, None, False),
            ("profile_without_kind_or_source", BUSINESS_KNOWLEDGE, None, False),
            ("profile_with_matching_source", REPORT_PROFILE, REPORT_SOURCE, False),
            ("profile_without_kind_given_source", BUSINESS_KNOWLEDGE, REPORT_SOURCE, True),
            ("profile_with_kind_missing_source", REPORT_PROFILE, None, True),
            ("profile_with_kind_other_source", REPORT_PROFILE, FLOW_SOURCE, True),
        ]
    )
    def test_check_task_source_matches_the_profile(
        self, _name: str, profile: TaskProfile | None, source: TaskSource | None, refused: bool
    ) -> None:
        with self.assertRaises(TaskSourceError) if refused else nullcontext():
            check_task_source(profile=profile, source=source)
