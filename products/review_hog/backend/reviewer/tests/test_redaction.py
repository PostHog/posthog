from parameterized import parameterized

from products.review_hog.backend.reviewer.tools.redaction import redact_secrets


class TestRedactSecrets:
    @parameterized.expand(
        [
            ("personal_api_key", "key phx_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789 used", "key [redacted] used", 1),
            ("secret_api_token", "phs_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789", "[redacted]", 1),
            (
                "oauth_tokens",
                "pha_AbCdEfGhIjKlMnOpQrStUv and phr_AbCdEfGhIjKlMnOpQrStUv",
                "[redacted] and [redacted]",
                2,
            ),
            ("ai_gateway_token", "AI_GATEWAY_TOKEN=phe_AbCdEfGhIjKlMnOpQrStUv", "AI_GATEWAY_TOKEN=[redacted]", 1),
            ("github_installation_token", "GH_TOKEN=ghs_abcdefghijklmnopqrstuvwxyz0123", "GH_TOKEN=[redacted]", 1),
            ("github_fine_grained_pat", "github_pat_11ABCDEFG0123456789_abcdefghijklmnop", "[redacted]", 1),
            (
                "clone_url",
                "origin https://x-access-token:ghs_abcdefghijklmnopqrstuvwxyz0123@github.com/posthog/posthog.git",
                "origin https://x-access-token:[redacted]@github.com/posthog/posthog.git",
                1,
            ),
            (
                "project_token_is_public",
                "phc_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
                "phc_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
                0,
            ),
            ("short_lookalike", "ghs_short and phx_short stay", "ghs_short and phx_short stay", 0),
            ("plain_text", "pytest: 14 passed, ruff clean", "pytest: 14 passed, ruff clean", 0),
        ]
    )
    def test_credential_shapes_are_redacted(self, _name: str, text: str, expected: str, count: int) -> None:
        assert redact_secrets(text) == (expected, count)
