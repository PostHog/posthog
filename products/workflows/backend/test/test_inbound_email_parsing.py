from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.services.inbound_email.parsing import (
    MAX_ATTACHMENTS,
    extract_reply_text,
    is_system_sender,
    parse_email,
    scrub_recipient_trace_headers,
)


class TestParseEmail(SimpleTestCase):
    def test_keeps_an_unusual_message_id_exactly(self) -> None:
        parsed = parse_email(b"From: a@example.com\r\nMessage-ID: <Re:-odd:id@example.com>\r\n\r\nhi\r\n")
        self.assertEqual(parsed.message_id, "<Re:-odd:id@example.com>")

    def test_survives_null_bytes_and_bad_encodings(self) -> None:
        parsed = parse_email(b"From: a\x00b@example.com\r\nSubject: nul\x00l\r\nX-Bad: \xff\xfe\r\n\r\nbo\x00dy\r\n")
        self.assertNotIn("\x00", parsed.subject + parsed.from_address + parsed.text)

    def test_a_hostile_filename_cannot_name_a_path(self) -> None:
        raw = (
            b"From: a@example.com\r\nContent-Type: multipart/mixed; boundary=b\r\n\r\n--b\r\n"
            b'Content-Disposition: attachment; filename="../../etc/pass<wd>"\r\n\r\nx\r\n--b--\r\n'
        )
        filename = parse_email(raw).attachments[0].filename
        self.assertNotIn("/", filename)
        self.assertNotIn("<", filename)

    def test_caps_attachments_and_counts_what_it_drops(self) -> None:
        parts = b"".join(
            b"--b\r\nContent-Disposition: attachment; filename=f%d\r\n\r\nx\r\n" % i for i in range(MAX_ATTACHMENTS + 5)
        )
        parsed = parse_email(
            b"From: a@example.com\r\nContent-Type: multipart/mixed; boundary=b\r\n\r\n" + parts + b"--b--"
        )
        self.assertEqual(len(parsed.attachments), MAX_ATTACHMENTS)
        self.assertEqual(parsed.attachments_dropped, 5)

    def test_inlines_a_referenced_image_but_never_an_svg(self) -> None:
        raw = (
            b"From: a@example.com\r\nContent-Type: multipart/related; boundary=b\r\n\r\n--b\r\n"
            b'Content-Type: text/html\r\n\r\n<img src="cid:one"><img src="cid:two">\r\n--b\r\n'
            b"Content-Type: image/png\r\nContent-ID: <one>\r\nContent-Transfer-Encoding: base64\r\n\r\nAAAA\r\n--b\r\n"
            b"Content-Type: image/svg+xml\r\nContent-ID: <two>\r\n\r\n<svg/>\r\n--b--\r\n"
        )
        html = parse_email(raw).html
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("cid:two", html)

    @parameterized.expand(
        [
            ("auto_replied", "Auto-Submitted: auto-replied\r\n", True),
            ("auto_submitted_no", "Auto-Submitted: no\r\n", False),
            ("precedence_auto", "Precedence: auto_reply\r\n", True),
            # A person writing through a mailing list still has to get through.
            ("precedence_list", "Precedence: list\r\n", False),
            ("x_autoreply", "X-Autoreply: yes\r\n", True),
            ("bounce", "Content-Type: multipart/report; boundary=z\r\n", True),
        ]
    )
    def test_auto_submitted(self, _name: str, header: str, expected: bool) -> None:
        self.assertEqual(parse_email(f"From: a@example.com\r\n{header}\r\nhi\r\n".encode()).auto_submitted, expected)

    @parameterized.expand(
        [
            ("empty", "", True),
            ("null", "<>", True),
            ("daemon", "MAILER-DAEMON@x.example", True),
            ("person", "a@x.example", False),
        ]
    )
    def test_system_sender(self, _name: str, envelope_from: str, expected: bool) -> None:
        self.assertEqual(is_system_sender(envelope_from), expected)


class TestScrubRecipientTraceHeaders(SimpleTestCase):
    def test_removes_every_header_that_can_name_another_recipient(self) -> None:
        raw = (
            b"Received: from a by b for <secret@other.example>;\r\n\tfolded <secret@other.example>\r\n"
            b"X-Forwarded-To: secret@other.example\r\nDelivered-To: secret@other.example\r\n"
            b"X-SES-Receipt: secret@other.example\r\nBcc: secret@other.example\r\n"
            b"Resent-Bcc: secret@other.example\r\n"
            b"From: a@example.com\r\nSubject: keep\r\n\r\nbody mentions secret@other.example\r\n"
        )
        scrubbed = scrub_recipient_trace_headers(raw)
        headers, _, body = scrubbed.partition(b"\r\n\r\n")
        self.assertNotIn(b"secret@other.example", headers)
        self.assertIn(b"Subject: keep", headers)
        self.assertIn(b"secret@other.example", body)


class TestExtractReplyText(SimpleTestCase):
    @parameterized.expand(
        [
            ("gmail", "Thanks!\n\nOn Tue, Nov 3, 2026 at 9:00 AM Acme <a@example.com> wrote:\n> old\n"),
            ("gmail_wrapped", "Thanks!\n\nOn Tue, Nov 3, 2026 at 9:00 AM Acme\n<a@example.com> wrote:\n> old\n"),
            ("french", "Thanks!\n\nLe mar. 3 nov. 2026 à 09:00, Acme <a@example.com> a écrit :\n> old\n"),
            ("german", "Thanks!\n\nAm 03.11.2026 um 09:00 schrieb Acme <a@example.com>:\n> old\n"),
            ("outlook", "Thanks!\n\nFrom: Acme <a@example.com>\nSent: Tuesday\nTo: me\nSubject: old\n\nold\n"),
            ("original_message", "Thanks!\n\n-----Original Message-----\nold\n"),
            ("bare_quote", "Thanks!\n\n> old\n> older\n"),
        ]
    )
    def test_keeps_only_what_the_sender_wrote(self, _name: str, text: str) -> None:
        self.assertEqual(extract_reply_text(text), "Thanks!")

    def test_a_long_run_of_blank_lines_stays_cheap(self) -> None:
        self.assertEqual(extract_reply_text("Thanks!" + "\n" * 500_000), "Thanks!")

    def test_returns_everything_when_the_whole_message_is_a_quote(self) -> None:
        self.assertEqual(extract_reply_text("> only a quote\n"), "> only a quote")
