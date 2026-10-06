from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.code_variables_masking import REDACTED, mask_code_variables

# Synthetic fakes, assembled at runtime so no complete credential literal sits in source.
STRIPE_KEY = "sk_live_" + "Zx81Qm7Lp2Vb9Nc4Rt6Yh3Kd"
BEARER_TOKEN = "tok_" + "Zx81Qm7Lp2Vb9Nc4"
BASIC_CREDENTIAL = "c3ZjOmZha2Ut" + "cGFzcy0xMjM="
PEM = "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQ"


class TestCodeVariablesMasking(SimpleTestCase):
    @parameterized.expand(
        [
            ("secret_name", {"api_key": "abc"}, {"api_key": REDACTED}),
            ("known_format", {"value": STRIPE_KEY}, {"value": REDACTED}),
            ("high_entropy", {"value": "Zx81Qm7Lp2Vb9Nc4Rt6Yh3Kd"}, {"value": REDACTED}),
            ("pem_key", {"value": PEM}, {"value": REDACTED}),
            (
                "url_credentials",
                {"url": "postgresql://app:hunter22@db.example.com/app"},
                {"url": f"postgresql://{REDACTED}@db.example.com/app"},
            ),
            (
                "url_credentials_end_at_the_authority",
                {"url": "https://app:hunter22@db.example.com?next=a@b"},
                {"url": f"https://{REDACTED}@db.example.com?next=a@b"},
            ),
            (
                "bearer_in_a_header_pair_list",
                {"headers": [["authorization", f"Bearer {BEARER_TOKEN}"]]},
                {"headers": [[REDACTED, f"Bearer {REDACTED}"]]},
            ),
            ("basic_under_a_neutral_name", {"value": f"Basic {BASIC_CREDENTIAL}"}, {"value": f"Basic {REDACTED}"}),
            ("short_basic_pair", {"value": "Basic YTpi"}, {"value": f"Basic {REDACTED}"}),
            ("lowercase_only_token", {"value": "Bearer zqwklmnopxyzrstu"}, {"value": f"Bearer {REDACTED}"}),
            (
                "dsn_after_the_scheme",
                {"value": "Bearer mongodb+srv://alice:sunflower99@db.example.com/app"},
                {"value": f"Bearer {REDACTED}://{REDACTED}@db.example.com/app"},
            ),
            ("colon_separator", {"value": f"Bearer: {BEARER_TOKEN}"}, {"value": f"Bearer: {REDACTED}"}),
            (
                "signed_url",
                {"url": "https://acct.blob.core.windows.net/c/f?sv=2022-11-02&sig=q2VxT8fKz1aB3dE%3D"},
                {"url": REDACTED},
            ),
            ("old_sdk_repr", {"settings": "Settings(AWS_SECRET_ACCESS_KEY='abc')"}, {"settings": REDACTED}),
            (
                "json_string_keeps_its_safe_fields",
                {"user": '{"name": "bob", "password": "hunter22"}'},
                {"user": f'{{"name":"bob","password":"{REDACTED}"}}'},
            ),
            ("sk_at_a_word_start", {"stripe_sk_key": "abc"}, {"stripe_sk_key": REDACTED}),
            (
                "distinct_placeholders",
                {"pools": {"password=a": 1, "password=b": 2}},
                {"pools": {"$$_posthog_redacted_key_0_$$": REDACTED, "$$_posthog_redacted_key_1_$$": REDACTED}},
            ),
            (
                "url_credentials_in_a_key",
                {"pools": {"postgresql://app:hunter22@db.example.com/app": 1}},
                {"pools": {f"postgresql://{REDACTED}@db.example.com/app": 1}},
            ),
        ]
    )
    def test_masks_what_cymbal_masks(self, _name: str, code_variables: dict, expected: dict) -> None:
        masked = mask_code_variables(code_variables)
        assert masked == expected
        # The command and cymbal can both mask the same frame.
        assert mask_code_variables(masked) == masked

    @parameterized.expand(
        [
            ("hello world",),
            ("design",),
            ("/signup?step=2",),
            ("the bearer of bad news",),
            ("bearer transportation",),
            ("basic: configuration",),
            ("basic: Configuration",),
            ("Basic Configuration loaded",),
            ("basicConfig(level=10)",),
            ("550e8400-e29b-41d4-a716-446655440000",),
            ("da39a3ee5e6b4b0d3255bfef95601890afd80709",),
            ("/usr/local/lib/python3.12/site-packages/app/views.py",),
            ('{"name": "bob"}',),
            ("disk_usage at 91%",),
            ("https://db.example.com?next=a:b@c",),
        ]
    )
    def test_leaves_benign_values_alone(self, value: str) -> None:
        assert mask_code_variables({"value": value}) == {"value": value}

    @parameterized.expand([("task_id",), ("disk_usage",)])
    def test_leaves_benign_names_alone(self, name: str) -> None:
        assert mask_code_variables({name: "42"}) == {name: "42"}
