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


INVOICE = "a" * 64


def _attachment(**fields: Any) -> dict[str, str]:
    return {"sha256": INVOICE, "filename": "invoice.pdf", **fields}


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
                "sha256_in_upper_case",
                {"attachments": [_attachment(sha256="A" * 64)]},
                ("attachments", 0, "sha256"),
                "invalid",
            ),
            (
                "attachment_without_a_sha256",
                {"attachments": [{"filename": "invoice.pdf"}]},
                ("attachments", 0, "sha256"),
                "required",
            ),
            (
                "attachment_with_inline_content",
                {"attachments": [_attachment(content="JVBERi0xLjQ=")]},
                ("attachments", 0, "content"),
                "unknown_attachment_field",
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
            ("too_many_bcc", {"bcc": [f"user{i}@example.com" for i in range(11)]}, ("bcc",), "max_length"),
            ("too_many_attachments", {"attachments": [_attachment()] * 11}, ("attachments",), "max_length"),
            ("too_many_attachments_that_are_also_invalid", {"attachments": [{}] * 11}, ("attachments",), "max_length"),
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
            ("too_many_bcc", "bcc", "max_length", "invalid_request", None, "at most 10 addresses"),
            ("too_many_attachments", "attachments", "max_length", "too_many_attachments", None, "at most 10 files"),
            (
                "filename_too_long",
                "attachments__0__filename",
                "max_length",
                "invalid_request",
                None,
                "`filename` to 255 characters",
            ),
            (
                "content_type_too_long",
                "attachments__0__content_type",
                "max_length",
                "invalid_request",
                None,
                "`content_type` to 78 characters",
            ),
            (
                "content_id_too_long",
                "attachments__0__content_id",
                "max_length",
                "invalid_request",
                None,
                "`content_id` to 78 characters",
            ),
            (
                "blocked_file_type",
                "attachments__0__filename",
                "blocked_file_type",
                "blocked_file_type",
                None,
                "a different file type",
            ),
            (
                "unsafe_filename",
                "attachments__0__filename",
                "unsafe_filename",
                "unsafe_filename",
                None,
                "only the file name",
            ),
            (
                "not_mime_type",
                "attachments__0__content_type",
                "not_mime_type",
                "not_mime_type",
                None,
                "leave `content_type` out",
            ),
            (
                "unsafe_content_id",
                "attachments__0__content_id",
                "unsafe_content_id",
                "unsafe_content_id",
                None,
                "as `cid:logo`",
            ),
            (
                "sha256_that_is_not_lowercase_hex",
                "attachments__0__sha256",
                "invalid",
                "invalid_request",
                None,
                "64 lowercase hex characters",
            ),
            (
                "file_sent_inline",
                "attachments__0__content",
                "unknown_attachment_field",
                "invalid_request",
                None,
                "messaging/attachments/uploads/",
            ),
            (
                "attachment_with_an_unknown_key",
                "attachments__0__contentId",
                "unknown_attachment_field",
                "invalid_request",
                None,
                "as `{sha256, filename}`",
            ),
            (
                "attachment_that_is_not_an_object",
                "attachments__0__non_field_errors",
                "invalid",
                "invalid_request",
                "attachments__0",
                "as `{sha256, filename}`",
            ),
            ("unparseable_copy_address", "cc__0", "invalid", "invalid_request", None, "bare addresses"),
            (
                "field_the_pipeline_lacks",
                "attachments",
                "field_not_accepted",
                "field_not_accepted",
                None,
                "without this field",
            ),
        ]
    )
    def test_explains_how_to_fix_a_refused_field(
        self, _name: str, attr: str, code: str, reported_code: str, reported_attr: str | None, fix: str
    ) -> None:
        refused = with_code_send_reason({"type": "validation_error", "code": code, "detail": "Refused.", "attr": attr})

        assert (refused["type"], refused["code"], refused["attr"]) == (
            "invalid_request",
            reported_code,
            reported_attr or attr,
        )
        assert fix in refused["fix"]

    @parameterized.expand(
        [
            ("one_address", {"cc": "copy@example.com"}),
            ("empty_lists", {"cc": [], "bcc": [], "attachments": []}),
            ("ten_addresses", {"bcc": [f"user{i}@example.com" for i in range(10)]}),
            ("ten_attachments", {"attachments": [_attachment()] * 10}),
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
            ("uploaded_files", {"attachments": [_attachment(), _attachment()]}, AttachmentSize(count=2, bytes=None)),
            ("a_file_that_is_not_an_object", {"attachments": ["invoice.pdf"]}, AttachmentSize(count=1, bytes=None)),
            ("attachments_that_are_not_a_list", {"attachments": "invoice.pdf"}, AttachmentSize(count=None, bytes=None)),
            ("a_body_that_is_not_an_object", ["invoice.pdf"], AttachmentSize(count=None, bytes=None)),
            (
                "a_form_body",
                QueryDict(f"attachments[0]filename=a.pdf&attachments[0]sha256={INVOICE}"),
                AttachmentSize(count=None, bytes=None),
            ),
        ]
    )
    def test_counts_the_files_and_leaves_their_bytes_to_the_pipeline(
        self, _name: str, body: Any, expected: AttachmentSize
    ) -> None:
        assert attachment_size(body) == expected
