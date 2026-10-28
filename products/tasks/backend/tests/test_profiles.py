from dataclasses import replace

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.profiles import (
    Read,
    TaskProfile,
    TaskProfileError,
    get_task_profile,
    register_task_profile,
    resolve_task_origin,
)

BUSINESS_KNOWLEDGE = get_task_profile("business_knowledge")


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
