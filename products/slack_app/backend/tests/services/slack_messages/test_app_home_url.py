from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import Integration

from products.slack_app.backend.services.slack_messages import app_home_url


class TestSlackLinks(SimpleTestCase):
    @parameterized.expand(
        [
            ("resolves", {"app_id": "A1"}, "T1", "slack://app?team=T1&id=A1&tab=home"),
            ("no_app_id", {}, "T1", None),
            ("no_workspace", {"app_id": "A1"}, "", None),
        ]
    )
    def test_app_home_url_needs_both_ids(
        self, _name: str, config: dict, integration_id: str, expected: str | None
    ) -> None:
        # Installs predating the OAuth path may carry no `app_id`; interpolating it anyway
        # would put an `app=None` link under every reply.
        integration = Integration(config=config, integration_id=integration_id)

        assert app_home_url(integration) == expected
