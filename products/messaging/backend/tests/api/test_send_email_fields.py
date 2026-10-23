from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.presentation.views.messaging_send import SendEmailSerializer


def rendered(**fields: Any) -> dict[str, Any]:
    return {
        "to": "user@example.com",
        "template_key": "welcome",
        "subject": "Welcome",
        "html": "<p>Hi</p>",
        **fields,
    }


class TestSendEmailFields(SimpleTestCase):
    def test_accepts_copies_headers_and_tags_on_a_code_send(self) -> None:
        body = SendEmailSerializer(
            data=rendered(
                cc=["jane@example.com"],
                bcc=["audit@example.com", "Archive@Example.com"],
                headers={"X-Entity-Ref-ID": "order-123", "List-Unsubscribe": "<https://example.com/unsubscribe>"},
                tags=[{"name": "category", "value": "password_reset"}, {"name": "plan-tier", "value": "pro"}],
            )
        )

        assert body.is_valid(), body.errors
        assert body.validated_data["cc"] == ["jane@example.com"]
        assert body.validated_data["bcc"] == ["audit@example.com", "Archive@Example.com"]
        assert body.validated_data["headers"] == {
            "X-Entity-Ref-ID": "order-123",
            "List-Unsubscribe": "<https://example.com/unsubscribe>",
        }
        assert body.validated_data["tags"] == [
            {"name": "category", "value": "password_reset"},
            {"name": "plan-tier", "value": "pro"},
        ]

    @parameterized.expand(
        [
            ("cc_not_an_address", {"cc": ["Jane"]}, "cc"),
            ("cc_with_a_display_name", {"cc": ["Jane <jane@example.com>"]}, "cc"),
            ("cc_quoted_with_a_comma", {"cc": ['"jane,admin"@example.com']}, "cc"),
            ("bcc_over_the_limit", {"bcc": [f"user{i}@example.com" for i in range(11)]}, "bcc"),
            ("header_posthog_sets", {"headers": {"Subject": "Hi"}}, "headers"),
            ("header_posthog_sets_any_case", {"headers": {"content-type": "text/plain"}}, "headers"),
            ("header_for_tracking", {"headers": {"X-PostHog-Tracking-Code": "x"}}, "headers"),
            ("header_for_the_mail_system", {"headers": {"Return-Path": "<a@example.com>"}}, "headers"),
            ("header_name_with_a_colon", {"headers": {"X-Ref:": "1"}}, "headers"),
            ("header_name_with_a_space", {"headers": {"X Ref": "1"}}, "headers"),
            ("header_value_with_a_line_break", {"headers": {"X-Ref": "1\r\nBcc: a@example.com"}}, "headers"),
            ("header_value_not_ascii", {"headers": {"X-Ref": "café"}}, "headers"),
            ("header_value_too_long", {"headers": {"X-Ref": "a" * 871}}, "headers"),
            ("header_twice_in_another_case", {"headers": {"X-Ref": "1", "x-ref": "2"}}, "headers"),
            ("headers_over_the_limit", {"headers": {f"X-Ref-{i}": "1" for i in range(11)}}, "headers"),
            ("tag_name_with_a_space", {"tags": [{"name": "my tag", "value": "a"}]}, "tags"),
            ("tag_value_with_a_dot", {"tags": [{"name": "plan", "value": "pro.v2"}]}, "tags"),
            ("tag_name_posthog_uses", {"tags": [{"name": "ph_id", "value": "a"}]}, "tags"),
            ("tag_twice", {"tags": [{"name": "plan", "value": "a"}, {"name": "plan", "value": "b"}]}, "tags"),
            ("tags_over_the_limit", {"tags": [{"name": f"tag{i}", "value": "a"} for i in range(11)]}, "tags"),
            ("tag_with_an_unknown_key", {"tags": [{"name": "plan", "value": "pro", "colour": "red"}]}, "tags"),
            ("reply_to_quoted_with_a_comma", {"reply_to": ['"a,b"@example.com']}, "reply_to"),
        ]
    )
    def test_refuses_a_field_it_cannot_send(self, _name: str, fields: dict[str, Any], attr: str) -> None:
        body = SendEmailSerializer(data=rendered(**fields))

        assert not body.is_valid()
        assert attr in body.errors, body.errors

    @parameterized.expand([("cc",), ("bcc",), ("headers",), ("tags",)])
    def test_refuses_code_send_fields_on_a_template_made_in_posthog(self, field: str) -> None:
        values: dict[str, Any] = {
            "cc": ["jane@example.com"],
            "bcc": ["jane@example.com"],
            "headers": {"X-Ref": "1"},
            "tags": [{"name": "plan", "value": "pro"}],
        }
        body = SendEmailSerializer(
            data={
                "to": "user@example.com",
                "template": {"id": "4c1f0c3c-8d1b-4a51-9f3a-0d8f1c0f6d2e"},
                field: values[field],
            }
        )

        assert not body.is_valid()
        assert field in body.errors, body.errors
