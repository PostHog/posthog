from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.signals.backend.utils import report_inbox_url


class TestReportInboxUrl(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_trailing_slash", "https://us.posthog.com"),
            ("trailing_slash", "https://us.posthog.com/"),
        ]
    )
    def test_builds_canonical_inbox_deep_link(self, _name: str, site_url: str) -> None:
        with override_settings(SITE_URL=site_url):
            assert report_inbox_url(2, "abc-123") == "https://us.posthog.com/project/2/inbox/reports/abc-123"
