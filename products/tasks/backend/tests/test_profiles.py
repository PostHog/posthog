from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.profiles import (
    LEGACY_PROFILE_KEYS,
    Read,
    TaskProfile,
    TaskProfileError,
    profile_for_origin,
    profile_for_task,
    register_task_profile,
)
from products.tasks.backend.models import Task


class TestTaskProfileRegistry(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{origin}_internal_{internal}", origin, internal, key)
            for (origin, internal), key in LEGACY_PROFILE_KEYS.items()
        ]
    )
    def test_unprofiled_task_resolves_through_the_legacy_mapping(
        self, _name: str, origin: str, internal: bool, key: str
    ) -> None:
        profile = profile_for_task(Task(origin_product=origin, internal=internal))

        self.assertEqual((profile.key, profile.origin_product, profile.listed), (key, origin, not internal))

    @parameterized.expand(
        [
            ("signals_research", "signal_report", True, "signals.research", "signals.research"),
            ("imported_conversation", "posthog_ai", False, "posthog_ai.imported", "posthog_ai.imported"),
            ("unregistered_key", "signal_report", True, "signals.retired", "signals.implementation"),
        ]
    )
    def test_stored_profile_wins_unless_unregistered(
        self, _name: str, origin: str, internal: bool, stored: str, expected: str
    ) -> None:
        task = Task(origin_product=origin, internal=internal, profile=stored)

        self.assertEqual(profile_for_task(task).key, expected)

    @parameterized.expand(
        [
            ("support_reply_listed", "support_reply", False, "support", "conversations"),
            ("review_hog_listed", "review_hog", False, None, "posthog_code"),
            ("experiments_internal", "experiments", True, None, "background_agents"),
            ("loop_internal", "loop", True, None, "posthog_code"),
            ("unknown_internal", "automation", True, None, "background_agents"),
        ]
    )
    def test_unmapped_legacy_pair_keeps_its_origin_behavior(
        self, _name: str, origin: str, internal: bool, mcp_agent: str | None, billing_product: str
    ) -> None:
        profile = profile_for_origin(origin, internal)

        self.assertEqual(
            (profile.mcp_agent, profile.billing_product, profile.listed, profile.personal_mcp),
            (mcp_agent, billing_product, not internal, not internal),
        )

    @parameterized.expand(
        [
            ("read_without_channel", {"read_without_channel": Read.TEAM}),
            ("idle_minutes", {"idle_minutes": 5}),
        ]
    )
    def test_rejects_a_profile_that_disagrees_with_its_origin(self, _name: str, overrides: dict) -> None:
        conflicting = TaskProfile(
            key="test.conflicting", origin_product="user_created", billing_product="posthog_code", **overrides
        )

        with self.assertRaises(TaskProfileError):
            register_task_profile(conflicting)
