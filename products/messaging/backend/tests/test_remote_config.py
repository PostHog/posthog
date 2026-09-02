from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.integration import Integration

from products.messaging.backend.remote_config import build_push_config


class TestBuildPushConfig(BaseTest):
    @parameterized.expand(
        [
            ("firebase reads project_id", [("firebase", {"project_id": "my-project"})], ["my-project"]),
            ("apns reads bundle_id", [("apns", {"bundle_id": "com.example.app"})], ["com.example.app"]),
            ("other kinds are ignored", [("slack", {"project_id": "my-project"})], []),
            ("a push kind without its id key", [("firebase", {}), ("apns", {})], []),
            (
                "non-string identifiers",
                [("apns", {"bundle_id": ["com.example.app"]}), ("firebase", {"project_id": 42})],
                [],
            ),
            (
                "deduped and sorted",
                [("firebase", {"project_id": "b"}), ("apns", {"bundle_id": "a"}), ("firebase", {"project_id": "a"})],
                ["a", "b"],
            ),
        ]
    )
    def test_push_config_lists_the_app_ids_a_device_can_register_against(self, _name, integrations, expected_app_ids):
        for kind, config in integrations:
            Integration.objects.create(team=self.team, kind=kind, config=config)

        assert build_push_config(self.team) == {"appIds": expected_app_ids}
