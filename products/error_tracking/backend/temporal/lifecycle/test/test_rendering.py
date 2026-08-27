from parameterized import parameterized

from products.error_tracking.backend.temporal.lifecycle.rendering import parse_origin, render_origin


class TestParseOrigin:
    @parameterized.expand(
        [
            (
                "production_host_from_current_url",
                {"$current_url": "https://app.example.com/dashboard?tab=1", "$lib": "posthog-js"},
                "app.example.com",
                False,
            ),
            (
                "localhost_with_port_is_dev",
                {"$current_url": "http://localhost:3000/dashboard", "$lib": "posthog-js"},
                "localhost:3000",
                True,
            ),
            (
                "loopback_ip_is_dev",
                {"$current_url": "http://127.0.0.1:8000/"},
                "127.0.0.1:8000",
                True,
            ),
            (
                "private_range_ip_is_dev",
                {"$current_url": "http://192.168.1.10/app"},
                "192.168.1.10",
                True,
            ),
            (
                "dot_local_hostname_is_dev",
                {"$current_url": "http://my-mac.local:5173/"},
                "my-mac.local:5173",
                True,
            ),
            (
                "host_used_when_current_url_absent",
                {"$host": "example.com", "$lib": "posthog-python"},
                "example.com",
                False,
            ),
            (
                "userinfo_is_dropped",
                {"$current_url": "https://user:secret@app.example.com/"},
                "app.example.com",
                False,
            ),
            (
                "ipv6_loopback_with_port_is_dev",
                {"$current_url": "http://[::1]:3000/p"},
                "[::1]:3000",
                True,
            ),
            (
                "host_fallback_drops_path_and_query",
                {"$host": "evil.example.com/admin?token=abc"},
                "evil.example.com",
                False,
            ),
            (
                "malformed_bracket_current_url_yields_no_host",
                {"$current_url": "https://a]b.example.com/"},
                None,
                False,
            ),
            (
                "malformed_bracket_host_yields_no_host",
                {"$host": "[unclosed"},
                None,
                False,
            ),
        ]
    )
    def test_parse_origin_host_and_dev_flag(
        self, _name: str, event_properties: dict[str, object], expected_host: str | None, expected_is_dev: bool
    ) -> None:
        origin = parse_origin(event_properties)
        assert origin.host == expected_host
        assert origin.is_dev_host is expected_is_dev

    def test_parse_origin_without_host(self) -> None:
        origin = parse_origin({"$lib": "posthog-js"})
        assert origin.host is None
        assert origin.is_dev_host is False


class TestRenderOrigin:
    def test_renders_dev_host_and_lib(self) -> None:
        origin = parse_origin({"$current_url": "http://localhost:3000/", "$lib": "posthog-js", "$lib_version": "1.2.3"})
        assert render_origin(origin) == "Origin: host localhost:3000 (local development host), lib posthog-js 1.2.3\n"

    def test_renders_production_host_without_dev_marker(self) -> None:
        origin = parse_origin({"$current_url": "https://app.example.com/", "$lib": "posthog-js"})
        assert render_origin(origin) == "Origin: host app.example.com, lib posthog-js\n"

    def test_empty_when_no_origin_fields(self) -> None:
        assert render_origin(parse_origin({})) == ""
