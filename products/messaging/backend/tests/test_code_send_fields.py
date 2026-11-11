import base64
from typing import Any

from django.http import QueryDict
from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.presentation.views.code_send_fields import (
    AttachmentSize,
    attachment_size,
    with_code_send_reason,
)
from products.messaging.backend.presentation.views.message_templates import SendEmailSerializer

ADDRESS_VERDICTS = [
    ("jane=tag@example.com", True),
    ("jane~tag@example.com", True),
    ("jane#tag@example.com", True),
    ("o'brien@example.com", True),
    ("a!b$c%d&e*f/g?h^i`j|k~l@example.com", True),
    ("jane@sub.example.co.uk", True),
    ("jane@bücher.example", False),
    ("jane@[192.0.2.1]", False),
    ('"jane doe"@example.com', False),
    ("jane@localhost", False),
    (".jane@example.com", False),
    ("jane.@example.com", False),
    ("jane..doe@example.com", False),
]


def _attachment(**fields: Any) -> dict[str, str]:
    return {"filename": "invoice.pdf", "content": "JVBERi0xLjQ=", **fields}


def _code_send(fields: dict[str, Any]) -> SendEmailSerializer:
    return SendEmailSerializer(
        data={"to": "user@example.com", "template_key": "welcome", "subject": "Hi", "text": "Hi", **fields}
    )


def _refusal_code(fields: dict[str, Any], *path: str | int) -> str:
    serializer = _code_send(fields)
    assert not serializer.is_valid()
    error: Any = serializer.errors
    for step in path:
        error = error[step]
    return (error[0] if isinstance(error, list) else error).code


class TestCodeSendFieldRefusals(SimpleTestCase):
    @parameterized.expand(
        [
            ("cc_with_a_display_name", {"cc": "Jane <jane@example.com>"}, ("cc", 0), "invalid"),
            ("cc_with_two_addresses_in_one", {"cc": "jane@example.com, joe@example.com"}, ("cc", 0), "invalid"),
            (
                "content_that_is_not_base64",
                {"attachments": [_attachment(content="not base64!")]},
                ("attachments", 0, "content"),
                "not_base64",
            ),
            ("empty_content", {"attachments": [_attachment(content="")]}, ("attachments", 0, "content"), "blank"),
            (
                "executable",
                {"attachments": [_attachment(filename="setup.EXE")]},
                ("attachments", 0, "filename"),
                "blocked_file_type",
            ),
            (
                "registry_file",
                {"attachments": [_attachment(filename="settings.reg")]},
                ("attachments", 0, "filename"),
                "blocked_file_type",
            ),
            (
                "executable_with_a_trailing_dot",
                {"attachments": [_attachment(filename="setup.exe.")]},
                ("attachments", 0, "filename"),
                "blocked_file_type",
            ),
            (
                "filename_with_a_path",
                {"attachments": [_attachment(), _attachment(filename="../invoice.pdf")]},
                ("attachments", 1, "filename"),
                "unsafe_filename",
            ),
            (
                "filename_with_a_line_break",
                {"attachments": [_attachment(filename="invoice\r\n.pdf")]},
                ("attachments", 0, "filename"),
                "unsafe_filename",
            ),
            (
                "content_type_that_is_not_a_mime_type",
                {"attachments": [_attachment(content_type="pdf")]},
                ("attachments", 0, "content_type"),
                "not_mime_type",
            ),
            (
                "content_id_with_brackets",
                {"attachments": [_attachment(content_id="<logo>")]},
                ("attachments", 0, "content_id"),
                "unsafe_content_id",
            ),
            (
                "attachment_that_is_not_an_object",
                {"attachments": ["invoice.pdf"]},
                ("attachments", 0, "non_field_errors"),
                "invalid",
            ),
            (
                "attachment_with_a_camel_case_key",
                {"attachments": [_attachment(contentId="logo")]},
                ("attachments", 0, "contentId"),
                "unknown_attachment_field",
            ),
            (
                "attachment_with_an_empty_key",
                {"attachments": [_attachment(**{"": "", "contentId": "logo"})]},
                ("attachments", 0, ""),
                "unknown_attachment_field",
            ),
            (
                "attachments_too_large",
                {"attachments": [_attachment(content=base64.b64encode(b"x" * 300_000).decode())] * 2},
                ("attachments",),
                "attachments_too_large",
            ),
            ("too_many_bcc", {"bcc": [f"user{i}@example.com" for i in range(11)]}, ("bcc",), "max_length"),
            ("too_many_attachments", {"attachments": [_attachment()] * 11}, ("attachments",), "max_length"),
            (
                "filename_too_long",
                {"attachments": [_attachment(filename="a" * 252 + ".pdf")]},
                ("attachments", 0, "filename"),
                "max_length",
            ),
            (
                "content_type_too_long",
                {"attachments": [_attachment(content_type=f"application/{'x' * 67}")]},
                ("attachments", 0, "content_type"),
                "max_length",
            ),
            (
                "content_id_too_long",
                {"attachments": [_attachment(content_id="x" * 79)]},
                ("attachments", 0, "content_id"),
                "max_length",
            ),
        ]
    )
    def test_refuses_an_extra_field_it_cannot_send(
        self, _name: str, fields: dict[str, Any], path: tuple[str | int, ...], code: str
    ) -> None:
        assert _refusal_code(fields, *path) == code

    @parameterized.expand(
        [
            ("too_many_bcc", "bcc", "max_length", "bcc", "at most 10 addresses"),
            ("too_many_attachments", "attachments", "max_length", "attachments", "at most 10 files"),
            ("filename_too_long", "attachments__0__filename", "max_length", None, "`filename` to 255 characters"),
            (
                "content_type_too_long",
                "attachments__0__content_type",
                "max_length",
                None,
                "`content_type` to 78 characters",
            ),
            ("content_id_too_long", "attachments__0__content_id", "max_length", None, "`content_id` to 78 characters"),
            ("attachments_too_large", "attachments", "attachments_too_large", None, "512 KB in total"),
            ("not_base64", "attachments__0__content", "not_base64", None, "Encode the file as standard base64"),
            ("blocked_file_type", "attachments__0__filename", "blocked_file_type", None, "a different file type"),
            ("unsafe_content_id", "attachments__0__content_id", "unsafe_content_id", None, "as `cid:logo`"),
            (
                "attachment_that_is_not_an_object",
                "attachments__0__non_field_errors",
                "invalid",
                "attachments__0",
                "as `{filename, content}`",
            ),
            ("unparseable_copy_address", "cc__0", "invalid", None, "bare addresses"),
            ("field_the_pipeline_lacks", "attachments", "field_not_accepted", None, "without this field"),
        ]
    )
    def test_explains_how_to_fix_a_refused_field(
        self, _name: str, attr: str, code: str, reported_attr: str | None, fix: str
    ) -> None:
        refused = with_code_send_reason({"type": "validation_error", "code": code, "detail": "Refused.", "attr": attr})

        assert (refused["type"], refused["code"], refused["attr"]) == (
            "invalid_request",
            "invalid_request",
            reported_attr or attr,
        )
        assert fix in refused["fix"]

    @parameterized.expand(
        [
            ("one_address", {"cc": "copy@example.com"}),
            ("empty_lists", {"cc": [], "bcc": [], "attachments": []}),
            ("ten_addresses", {"bcc": [f"user{i}@example.com" for i in range(10)]}),
            (
                "attachments_at_the_size_limit",
                {"attachments": [_attachment(content=base64.b64encode(b"x" * 262_144).decode())] * 2},
            ),
        ]
    )
    def test_accepts_extra_fields_at_their_limits(self, _name: str, fields: dict[str, Any]) -> None:
        serializer = _code_send(fields)

        assert serializer.is_valid(), serializer.errors

    @parameterized.expand(
        [
            *(("cc", address, accepted) for address, accepted in ADDRESS_VERDICTS),
            ("bcc", "jane=tag@example.com", True),
            ("bcc", "jane@localhost", False),
        ]
    )
    def test_takes_the_copy_addresses_the_pipeline_takes(self, field: str, address: str, accepted: bool) -> None:
        if accepted:
            serializer = _code_send({field: [address]})
            assert serializer.is_valid(), serializer.errors
            assert serializer.validated_data[field] == [address]
        else:
            assert _refusal_code({field: [address]}, field, 0) == "invalid"


class TestAttachmentSize(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_attachments_field", {}, AttachmentSize(count=0, bytes=0)),
            ("null_attachments", {"attachments": None}, AttachmentSize(count=0, bytes=0)),
            ("empty_attachments", {"attachments": []}, AttachmentSize(count=0, bytes=0)),
            (
                "files_with_and_without_padding",
                {
                    "attachments": [
                        _attachment(content="YSxi"),
                        _attachment(content="aGk="),
                        _attachment(content="aQ=="),
                    ]
                },
                AttachmentSize(count=3, bytes=6),
            ),
            (
                "a_file_over_the_inline_limit",
                {"attachments": [_attachment(content=base64.b64encode(b"x" * 600_001).decode())]},
                AttachmentSize(count=1, bytes=600_001),
            ),
            (
                "one_file_that_is_not_base64",
                {"attachments": [_attachment(content="YSxi"), _attachment(content="not base64!")]},
                AttachmentSize(count=2, bytes=None),
            ),
            (
                "base64_without_its_padding",
                {"attachments": [_attachment(content="aGk")]},
                AttachmentSize(count=1, bytes=None),
            ),
            ("a_file_without_content", {"attachments": [{"filename": "a.pdf"}]}, AttachmentSize(count=1, bytes=None)),
            ("a_file_that_is_not_an_object", {"attachments": ["invoice.pdf"]}, AttachmentSize(count=1, bytes=None)),
            ("attachments_that_are_not_a_list", {"attachments": "invoice.pdf"}, AttachmentSize(count=None, bytes=None)),
            ("a_body_that_is_not_an_object", ["invoice.pdf"], AttachmentSize(count=None, bytes=None)),
            (
                "a_form_body",
                QueryDict("attachments[0]filename=a.pdf&attachments[0]content=aGk%3D"),
                AttachmentSize(count=None, bytes=None),
            ),
        ]
    )
    def test_counts_the_decoded_bytes_only_when_every_file_is_base64(
        self, _name: str, body: Any, expected: AttachmentSize
    ) -> None:
        assert attachment_size(body) == expected
