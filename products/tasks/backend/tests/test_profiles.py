from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.profiles import (
    LEGACY_PROFILE_KEYS,
    Read,
    TaskProfile,
    TaskProfileError,
    get_task_profile,
    profile_for_origin,
    register_task_profile,
)


class TestTaskProfileRegistry(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{origin}_internal_{internal}", origin, internal, key)
            for (origin, internal), key in LEGACY_PROFILE_KEYS.items()
        ]
    )
    def test_legacy_mapping_resolves_to_a_matching_profile(
        self, _name: str, origin: str, internal: bool, key: str
    ) -> None:
        profile = get_task_profile(key)

        self.assertEqual((profile.origin_product, profile.listed), (origin, not internal))

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
