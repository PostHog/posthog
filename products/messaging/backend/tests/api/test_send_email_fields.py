import base64
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


INVITE = base64.b64encode(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n").decode()


def attachment(**fields: Any) -> dict[str, Any]:
    return {"filename": "invite.ics", "content": INVITE, **fields}


class TestSendEmailAttachments(SimpleTestCase):
    def test_accepts_attachments_and_decodes_their_content(self) -> None:
        body = SendEmailSerializer(
            data=rendered(
                attachments=[
                    attachment(content_type="text/calendar; method=REQUEST"),
                    attachment(filename="logo.png", content="iVBORw0KGgo=", content_id="logo"),
                ]
            )
        )

        assert body.is_valid(), body.errors
        assert body.validated_data["attachments"] == [
            {
                "filename": "invite.ics",
                "content": b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
                "content_type": "text/calendar; method=REQUEST",
            },
            {"filename": "logo.png", "content": b"\x89PNG\r\n\x1a\n", "content_id": "logo"},
        ]

    @parameterized.expand(
        [
            ("not_base64", [attachment(content="not base64!")]),
            ("empty", [attachment(content="")]),
            ("over_the_total_size", [attachment(content=base64.b64encode(b"a" * 300_000).decode())] * 2),
            ("over_the_count", [attachment(filename=f"file{i}.txt") for i in range(11)]),
            ("blocked_extension", [attachment(filename="setup.EXE")]),
            ("blocked_extension_with_a_trailing_dot", [attachment(filename="setup.exe. ")]),
            ("filename_with_a_line_break", [attachment(filename="invite\r\n.ics")]),
            ("filename_with_a_path", [attachment(filename="../invite.ics")]),
            ("filename_too_long", [attachment(filename="a" * 252 + ".ics")]),
            ("content_type_with_a_line_break", [attachment(content_type="text/plain\r\nBcc: a@example.com")]),
            ("content_type_not_a_type", [attachment(content_type="calendar")]),
            ("content_id_with_brackets", [attachment(content_id="<logo>")]),
            ("content_id_too_long", [attachment(content_id="a" * 129)]),
        ]
    )
    def test_refuses_an_attachment_it_cannot_send(self, _name: str, attachments: list[dict[str, Any]]) -> None:
        body = SendEmailSerializer(data=rendered(attachments=attachments))

        assert not body.is_valid()
        assert "attachments" in body.errors, body.errors
        assert INVITE not in str(body.errors)

    def test_refuses_attachments_on_a_template_made_in_posthog(self) -> None:
        body = SendEmailSerializer(
            data={
                "to": "user@example.com",
                "template": {"id": "4c1f0c3c-8d1b-4a51-9f3a-0d8f1c0f6d2e"},
                "attachments": [attachment()],
            }
        )

        assert not body.is_valid()
        assert "attachments" in body.errors, body.errors
