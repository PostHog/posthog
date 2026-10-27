from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.profiles import (
    Read,
    TaskProfile,
    TaskProfileError,
    register_task_profile,
    resolve_task_origin,
)
from products.tasks.backend.task_profiles import TASK_ANALYSIS


class TestTaskProfileRegistry(SimpleTestCase):
    @parameterized.expand(
        [
            ("read_without_channel", {"read_without_channel": Read.TEAM}),
            ("idle_minutes", {"idle_minutes": 5}),
        ]
    )
    def test_rejects_a_profile_that_disagrees_with_its_origin(self, _name: str, overrides: dict) -> None:
        conflicting = TaskProfile(
            key="test.conflicting", origin_product="task_analysis", billing_product="background_agents", **overrides
        )

        with self.assertRaises(TaskProfileError):
            register_task_profile(conflicting)

    @parameterized.expand(
        [
            ("profile_only", TASK_ANALYSIS, None, None, ("task_analysis", True, "task_analysis")),
            (
                "profile_and_matching_origin",
                TASK_ANALYSIS,
                "task_analysis",
                True,
                ("task_analysis", True, "task_analysis"),
            ),
            ("origin_only", None, "task_analysis", True, ("task_analysis", True, None)),
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
            ("origin_mismatch", TASK_ANALYSIS, "loop", None),
            ("internal_mismatch", TASK_ANALYSIS, None, False),
        ]
    )
    def test_resolve_task_origin_rejects_conflicting_input(
        self, _name: str, profile: TaskProfile | None, origin: str | None, internal: bool | None
    ) -> None:
        with self.assertRaises(TaskProfileError):
            resolve_task_origin(profile=profile, origin_product=origin, internal=internal)
