from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.test.anti_ssrf import mock_anti_ssrf_dns_lookup

from products.user_journeys.backend.logic.run_urls import TeamUrlPolicy

AUTHORIZED = ["https://shop.example.com", "https://*.preview.example.com", "http://127.0.0.1:8000", "http://10.0.0.5"]


class TestTeamUrlPolicy(SimpleTestCase):
    @parameterized.expand(
        [
            ("authorized_host", "https://shop.example.com/pricing", ["93.184.216.34"], None),
            ("authorized_wildcard", "https://pr-7.preview.example.com/", ["93.184.216.34"], None),
            ("unauthorized_host", "https://evil.example.org/", ["93.184.216.34"], "authorized URLs"),
            ("authorized_loopback", "http://127.0.0.1:8000/", [], "can't be reached"),
            ("authorized_private_ip", "http://10.0.0.5/admin", [], "can't be reached"),
            ("authorized_host_resolving_private", "https://shop.example.com/", ["10.1.2.3"], "can't be reached"),
            ("metadata_service", "http://169.254.169.254/latest/meta-data/", [], "authorized URLs"),
            ("credentials_in_url", "https://user:pw@shop.example.com/", ["93.184.216.34"], "user name"),
            ("not_http", "file:///etc/passwd", [], "http://"),
        ]
    )
    def test_page_error(self, _name: str, url: str, resolves_to: list[str], expected: str | None) -> None:
        with mock_anti_ssrf_dns_lookup(resolves_to=resolves_to):
            error = TeamUrlPolicy(AUTHORIZED).page_error(url)
        if expected is None:
            assert error is None
        else:
            assert error is not None and expected in error

    @parameterized.expand(
        [
            ("public_cdn", "https://cdn.example.net/app.js", ["93.184.216.34"], True),
            ("inline_data", "data:image/png;base64,AAAA", [], True),
            ("metadata_service", "http://169.254.169.254/latest/meta-data/", [], False),
            ("host_resolving_private", "https://internal.example.net/", ["192.168.1.10"], False),
            ("loopback", "http://localhost:6379/", [], False),
            ("not_http", "file:///etc/passwd", [], False),
        ]
    )
    def test_request_error(self, _name: str, url: str, resolves_to: list[str], allowed: bool) -> None:
        with mock_anti_ssrf_dns_lookup(resolves_to=resolves_to):
            assert (TeamUrlPolicy(AUTHORIZED).request_error(url) is None) is allowed

    def test_pages_and_requests_on_one_host_share_one_lookup(self) -> None:
        policy = TeamUrlPolicy(AUTHORIZED)
        with mock_anti_ssrf_dns_lookup() as lookup:
            assert policy.page_error("https://shop.example.com/") is None
            assert policy.page_error("https://shop.example.com/pricing") is None
            assert policy.request_error("https://shop.example.com/app.js") is None
            assert policy.request_error("https://cdn.example.net/app.js") is None

        assert lookup.call_count == 2
