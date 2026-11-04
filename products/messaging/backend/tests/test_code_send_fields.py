import base64
from typing import Any

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.presentation.views.code_send_fields import CodeSendFieldRefused
from products.messaging.backend.presentation.views.message_templates import SendEmailSerializer


def _attachment(**fields: Any) -> dict[str, str]:
    return {"filename": "invoice.pdf", "content": "JVBERi0xLjQ=", **fields}


def _refusal(fields: dict[str, Any]) -> CodeSendFieldRefused:
    body = {"to": "user@example.com", "template_key": "welcome", "subject": "Hi", "text": "Hi", **fields}
    with pytest.raises(CodeSendFieldRefused) as refused:
        SendEmailSerializer(data=body).is_valid(raise_exception=True)
    return refused.value


class TestCodeSendFieldRefusals(SimpleTestCase):
    @parameterized.expand(
        [
            ("cc_with_a_display_name", {"cc": "Jane <jane@example.com>"}, "cc__0"),
            ("cc_with_a_quoted_local_part", {"cc": ['"jane doe"@example.com']}, "cc__0"),
            ("cc_with_two_addresses_in_one", {"cc": "jane@example.com, joe@example.com"}, "cc__0"),
            ("cc_with_an_ip_literal_domain", {"cc": ["jane@[192.0.2.1]"]}, "cc__0"),
            ("bcc_with_a_non_ascii_domain", {"bcc": ["jane@bücher.example"]}, "bcc__0"),
            (
                "content_that_is_not_base64",
                {"attachments": [_attachment(content="not base64!")]},
                "attachments__0__content",
            ),
            ("empty_content", {"attachments": [_attachment(content="")]}, "attachments__0__content"),
            ("executable", {"attachments": [_attachment(filename="setup.EXE")]}, "attachments__0__filename"),
            (
                "executable_with_a_trailing_dot",
                {"attachments": [_attachment(filename="setup.exe.")]},
                "attachments__0__filename",
            ),
            (
                "filename_with_a_path",
                {"attachments": [_attachment(), _attachment(filename="../invoice.pdf")]},
                "attachments__1__filename",
            ),
            (
                "filename_with_a_line_break",
                {"attachments": [_attachment(filename="invoice\r\n.pdf")]},
                "attachments__0__filename",
            ),
            (
                "content_type_that_is_not_a_mime_type",
                {"attachments": [_attachment(content_type="pdf")]},
                "attachments__0__content_type",
            ),
            (
                "content_id_with_brackets",
                {"attachments": [_attachment(content_id="<logo>")]},
                "attachments__0__content_id",
            ),
            ("attachment_that_is_not_an_object", {"attachments": ["invoice.pdf"]}, "attachments__0"),
            (
                "attachment_with_a_camel_case_key",
                {"attachments": [_attachment(contentId="logo")]},
                "attachments__0__contentId",
            ),
            (
                "attachment_with_an_empty_key",
                {"attachments": [_attachment(**{"": "", "contentId": "logo"})]},
                "attachments__0__",
            ),
            (
                "attachments_too_large",
                {"attachments": [_attachment(content=base64.b64encode(b"x" * 300_000).decode())] * 2},
                "attachments",
            ),
        ]
    )
    def test_refuses_an_extra_field_it_cannot_send(self, _name: str, fields: dict[str, Any], attr: str) -> None:
        refused = _refusal(fields)

        assert refused.get_codes() == {attr: "invalid_request"}
        assert refused.why and refused.fix

    @parameterized.expand(
        [
            ("too_many_bcc", {"bcc": [f"user{i}@example.com" for i in range(11)]}, "bcc", "at most 10 addresses"),
            ("too_many_attachments", {"attachments": [_attachment()] * 11}, "attachments", "at most 10 files"),
            (
                "filename_too_long",
                {"attachments": [_attachment(filename="a" * 252 + ".pdf")]},
                "attachments__0__filename",
                "255 characters",
            ),
        ]
    )
    def test_explains_the_limit_a_refused_field_passed(
        self, _name: str, fields: dict[str, Any], attr: str, fix: str
    ) -> None:
        refused = _refusal(fields)

        assert refused.get_codes() == {attr: "invalid_request"}
        assert fix in refused.fix

    @parameterized.expand(
        [
            ("one_address", {"cc": "copy@example.com"}),
            ("empty_lists", {"cc": [], "bcc": [], "attachments": []}),
            (
                "addresses_with_atext_symbols",
                {
                    "cc": ["copy+tag@example.com", "o'neil@example.com"],
                    "bcc": ["jane=tag@example.com", "jane~tag@example.com"],
                },
            ),
            ("ten_addresses", {"bcc": [f"user{i}@example.com" for i in range(10)]}),
            (
                "attachments_at_the_size_limit",
                {"attachments": [_attachment(content=base64.b64encode(b"x" * 262_144).decode())] * 2},
            ),
        ]
    )
    def test_accepts_extra_fields_at_their_limits(self, _name: str, fields: dict[str, Any]) -> None:
        body = {"to": "user@example.com", "template_key": "welcome", "subject": "Hi", "text": "Hi", **fields}

        assert SendEmailSerializer(data=body).is_valid(), SendEmailSerializer(data=body).errors
