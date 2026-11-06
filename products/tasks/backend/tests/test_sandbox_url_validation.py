import pytest

from django.test import override_settings

from products.tasks.backend.presentation.views.api import TaskRunViewSet


class TestIsValidSandboxUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://abc123.modal.host/command", True),
            ("https://abc.modal.run/events", True),
            ("https://hogland.prod-us.posthog.dev/v1/hogboxes/hb-1/proxy/8080/command", True),
            # The real box-proxy URL shape from production (box ids, port path segment).
            ("https://hogland.prod-us.posthog.dev/v1/hogboxes/box-2e04766e124b/proxy/8080/command", True),
            # An attacker-shaped lookalike host must not pass the exact-host check.
            ("https://hogland.prod-us.posthog.dev.evil.example/command", False),
            ("https://evil.example/command", False),
            ("http://hogland.prod-us.posthog.dev/command", False),
            # The hogland entry is an exact origin: a different port is a different origin.
            ("https://hogland.prod-us.posthog.dev:8443/command", False),
        ],
    )
    @override_settings(HOGLAND_API_URL="https://hogland.prod-us.posthog.dev")
    def test_allowlist(self, url, expected):
        assert TaskRunViewSet._is_valid_sandbox_url(url) is expected

    def test_hogland_host_not_allowed_when_unconfigured(self):
        with override_settings(HOGLAND_API_URL=None):
            assert not TaskRunViewSet._is_valid_sandbox_url(
                "https://hogland.prod-us.posthog.dev/v1/hogboxes/hb-1/proxy/8080/command"
            )

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://hogland.prod-us.posthog.dev:8443/command", True),
            # Portless is a different origin when the configured URL pins a port.
            ("https://hogland.prod-us.posthog.dev/command", False),
        ],
    )
    @override_settings(HOGLAND_API_URL="https://hogland.prod-us.posthog.dev:8443")
    def test_hogland_origin_match_includes_port(self, url, expected):
        assert TaskRunViewSet._is_valid_sandbox_url(url) is expected
