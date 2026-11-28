"""Turns raw MIME from a stranger into bounded, plain data. Everything read here is attacker-controlled."""

import re
import email
import base64
from collections.abc import Iterable
from email.message import EmailMessage, Message
from email.policy import EmailPolicy
from email.utils import getaddresses, parseaddr
from typing import Any

from posthog.dataclasses import frozen

MAX_RAW_BYTES = 40 * 1024 * 1024
MAX_BODY_CHARS = 1024 * 1024
MAX_PARTS = 500
MAX_ATTACHMENTS = 100
MAX_HEADERS = 200
MAX_HEADER_VALUE_CHARS = 8 * 1024
MAX_ADDRESSES = 100
MAX_ADDRESS_CHARS = 320
MAX_SUBJECT_CHARS = 1000
MAX_MESSAGE_ID_CHARS = 512
MAX_FILENAME_CHARS = 255
MAX_INLINE_IMAGE_BYTES = 512 * 1024
MAX_INLINE_IMAGES_BYTES = 5 * 1024 * 1024
# The standard library's header parser and MIME walker get far slower and larger than the input they are given, so a
# message outside these limits is kept unparsed. Ordinary mail stays well inside them.
MAX_HEADER_BLOCK_BYTES = 64 * 1024
MAX_PARSED_HEADER_CHARS = 32 * 1024
MAX_PARSED_HEADER_CHARS_PER_MESSAGE = 2 * 1024 * 1024
MAX_BOUNDARY_LINES = 2_000
MAX_BOUNDARY_DECLARATIONS = 50
MAX_LINE_BREAKS = 2_000_000

# An SVG can carry script, so only formats a browser treats as pure pixels are inlined.
INLINE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

# Trace headers can name other envelope recipients, which is what makes a Bcc private.
RECIPIENT_TRACE_HEADERS = frozenset(
    {
        "bcc",
        "resent-bcc",
        "received",
        "delivered-to",
        "envelope-to",
        "x-original-to",
        "x-forwarded-to",
        "x-envelope-to",
        "x-rcpt-to",
        "return-receipt-to",
    }
)

VISIBLE_RECIPIENT_HEADERS = frozenset({"to", "cc"})

MAX_REFERENCES = 50
_MESSAGE_ID = re.compile(r"<[^<>\s]{1,500}>")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_END_OF_HEADERS = re.compile(rb"\r?\n\r?\n")
_BOUNDARY_DECLARATION = re.compile(rb"boundary\*?\d*\*?\s*=", re.IGNORECASE)
_FOLD = re.compile(r"\r?\n[ \t]+")
_FILENAME_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')
_CID_REFERENCE = re.compile(r"""cid:([^"'\s>)]+)""", re.IGNORECASE)

AUTO_REPLY_PRECEDENCE = frozenset({"auto_reply", "auto-reply", "junk"})
SYSTEM_SENDER_LOCAL_PARTS = frozenset({"mailer-daemon", "postmaster"})

# Each pattern matches a line, or a line and the next one, that starts the quoted part of a reply, in the wordings mail
# clients use by default. A stranger writes the text, so the patterns only ever see one bounded line at a time.
MAX_QUOTE_LINE_CHARS = 1000
_QUOTE_ATTRIBUTIONS = (
    re.compile(r"On\s.{1,300}\swrote:"),
    re.compile(r"Le\s.{1,300}\sa\s[ée]crit\s?:"),
    re.compile(r"Am\s.{1,300}\sschrieb\s.{0,200}:"),
    re.compile(r"El\s.{1,300}\sescribi[óo]\s?:"),
    re.compile(r"Op\s.{1,300}\sschreef\s.{0,200}:"),
)
_QUOTE_SEPARATOR = re.compile(r"-{2,}\s*(Original Message|Forwarded message)\s*-{2,}|_{20,}", re.IGNORECASE)
_OUTLOOK_FROM = re.compile(r"From:\s.+")
_OUTLOOK_SENT = re.compile(r"(Sent|Date):\s.+")
_QUOTED_LINE = re.compile(r"^\s*>")
# Parsers disagree about routes, comments, groups and encoded words, so a From with any of them proves nothing.
_ADDR_SPEC = r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
_STRICT_FROM = re.compile(
    rf"""\s*(?:(?P<bare>{_ADDR_SPEC})|(?:"(?:[^"\\]|\\.)*"|[^"<>@,;:()\\]*)\s*<(?P<angled>{_ADDR_SPEC})>)\s*"""
)
_ANGLED_ADDRESS = re.compile(r"<([^<>]*)>\s*$")


class MessageTooComplex(Exception):
    """Not a ValueError, so the handlers that forgive one bad header let this end the whole parse."""


class _HeaderBudget:
    def __init__(self) -> None:
        self.chars_left = MAX_PARSED_HEADER_CHARS_PER_MESSAGE


class _BoundedPolicy(EmailPolicy):
    """All header parsing passes through here, including the headers of MIME parts and attached messages."""

    budget: _HeaderBudget | None = None

    def header_fetch_parse(self, name: str, value: str) -> Any:
        if self.budget is not None:
            self.budget.chars_left -= len(value)
            if len(value) > MAX_PARSED_HEADER_CHARS or self.budget.chars_left < 0:
                raise MessageTooComplex(f"{name} header")
        return super().header_fetch_parse(name, value)


@frozen
class ParsedAttachment:
    index: int
    filename: str
    content_type: str
    size: int
    content: bytes
    content_id: str
    inline: bool


@frozen
class _Parts:
    text: str
    html: str
    attachments: list[ParsedAttachment]
    dropped: int


@frozen
class _Sender:
    name: str
    address: str


@frozen
class ParsedHeader:
    name: str
    value: str


@frozen
class ParsedEmail:
    from_address: str
    from_name: str
    subject: str
    message_id: str
    in_reply_to: str
    references: tuple[str, ...]
    to_addresses: tuple[str, ...]
    cc_addresses: tuple[str, ...]
    reply_to_addresses: tuple[str, ...]
    text: str
    html: str
    reply_text: str
    body_truncated: bool
    headers: tuple[ParsedHeader, ...]
    attachments: tuple[ParsedAttachment, ...]
    attachments_dropped: int
    auto_submitted: bool
    # Empty unless the message has exactly one From header holding exactly one plainly written address.
    verifiable_from_address: str


def parse_email(raw: bytes) -> ParsedEmail:
    _check_parse_limits(raw)
    # refold_source="none" serializes an attached message without parsing its headers again.
    message = email.message_from_bytes(raw, policy=_BoundedPolicy(refold_source="none", budget=_HeaderBudget()))  # type: ignore[call-overload]
    sender = _single_address(_header(message, "from"))
    parts = _walk_parts(message)
    text, text_truncated = _bounded(parts.text)
    html, html_truncated = _bounded(_inline_images(parts.html, parts.attachments))
    return ParsedEmail(
        from_address=sender.address,
        from_name=sender.name,
        subject=_clean(_header(message, "subject"))[:MAX_SUBJECT_CHARS],
        message_id=_clean(_unparsed_header(message, "message-id"))[:MAX_MESSAGE_ID_CHARS],
        in_reply_to=_clean(_unparsed_header(message, "in-reply-to"))[:MAX_MESSAGE_ID_CHARS],
        references=_message_ids(_encodable(_unparsed_header(message, "references"))),
        to_addresses=_addresses(_header(message, "to")),
        cc_addresses=_addresses(_header(message, "cc")),
        reply_to_addresses=_addresses(_header(message, "reply-to")),
        text=text,
        html=html,
        reply_text=extract_reply_text(text),
        body_truncated=text_truncated or html_truncated,
        headers=_headers(message),
        attachments=tuple(parts.attachments),
        attachments_dropped=parts.dropped,
        auto_submitted=is_auto_submitted(message),
        verifiable_from_address=_verifiable_from(message),
    )


def strict_address(value: str) -> str:
    """The lowercased address when `value` is plainly one address, optionally with a display name. Otherwise empty."""
    match = _STRICT_FROM.fullmatch(_FOLD.sub(" ", value))
    return (match.group("bare") or match.group("angled")).lower() if match else ""


def address_from_receipt(values: Any) -> str:
    """The sender SES read from the message. Its From list holds decoded display names, so only the address is strict."""
    if not isinstance(values, list) or len(values) != 1:
        return ""
    value = str(values[0])[: MAX_ADDRESS_CHARS * 2]
    angled = _ANGLED_ADDRESS.search(value)
    return strict_address(angled.group(1) if angled else value)


def is_auto_submitted(message: Message) -> bool:
    """True for out-of-office replies, bounces and other mail a machine wrote in answer to mail.

    A person relayed through a mailing list still counts as a person, so `Precedence: list` and `bulk` stay accepted.
    """
    auto_submitted = _header(message, "auto-submitted").strip().lower()
    if auto_submitted and not auto_submitted.startswith("no"):
        return True
    if _header(message, "precedence").strip().lower() in AUTO_REPLY_PRECEDENCE:
        return True
    if _header(message, "x-autoreply") or _header(message, "x-autorespond"):
        return True
    if message.get_content_type() == "multipart/report":
        return True
    return False


def is_system_sender(envelope_from: str) -> bool:
    """A null return path means a bounce or an auto-reply, as RFC 3834 asks of responders."""
    address = envelope_from.strip().strip("<>").lower()
    return not address or address.partition("@")[0] in SYSTEM_SENDER_LOCAL_PARTS


def scrub_recipient_trace_headers(raw: bytes, named_elsewhere: Iterable[str] = ()) -> bytes:
    """Remove the headers that could name another team's envelope recipients from one team's copy of a message.

    A name list can't cover every header a mail server may add, so any header naming such a recipient goes too. To and
    Cc stay, because the sender already showed those addresses to everyone who gets the message.
    """
    separator = _END_OF_HEADERS.search(raw)
    header_block, rest = (raw[: separator.start()], raw[separator.start() :]) if separator else (raw, b"")
    elsewhere = tuple(address.lower().encode("utf-8", errors="replace") for address in named_elsewhere)
    kept: list[bytes] = []
    for field in _header_fields(header_block):
        name = field.partition(b":")[0].strip().lower().decode("ascii", errors="replace")
        if name in RECIPIENT_TRACE_HEADERS or name.startswith("x-ses-"):
            continue
        unfolded = field.replace(b"\r", b"").replace(b"\n", b"").lower()
        if name not in VISIBLE_RECIPIENT_HEADERS and any(address in unfolded for address in elsewhere):
            continue
        kept.append(field)
    return b"".join(kept) + rest


def extract_reply_text(text: str) -> str:
    """The part of a reply the sender wrote, or the whole text when no quote is found. Best effort."""
    if not text:
        return ""
    lines = text.splitlines()
    cut = len(lines)
    for index, line in enumerate(lines):
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if _starts_quote(line, next_line):
            cut = index
            break
    kept = lines[:cut]
    while kept and (not kept[-1].strip() or _QUOTED_LINE.match(kept[-1])):
        kept.pop()
    reply = "\n".join(line for line in kept if not _QUOTED_LINE.match(line)).strip()
    return reply or text.strip()


def _starts_quote(line: str, next_line: str) -> bool:
    current = line.strip()[:MAX_QUOTE_LINE_CHARS]
    if not current:
        return False
    following = next_line.strip()[:MAX_QUOTE_LINE_CHARS]
    if _QUOTE_SEPARATOR.fullmatch(current):
        return True
    if _OUTLOOK_FROM.fullmatch(current) and _OUTLOOK_SENT.fullmatch(following):
        return True
    wrapped = f"{current} {following}"
    return any(pattern.fullmatch(current) or pattern.fullmatch(wrapped) for pattern in _QUOTE_ATTRIBUTIONS)


def _check_parse_limits(raw: bytes) -> None:
    separator = _END_OF_HEADERS.search(raw, 0, MAX_HEADER_BLOCK_BYTES + 4)
    if separator is None and len(raw) > MAX_HEADER_BLOCK_BYTES:
        raise MessageTooComplex("header block")
    # The parser treats a bare CR as a line break too, and checks every line against every enclosing boundary.
    if raw.count(b"\n") + raw.count(b"\r") > MAX_LINE_BREAKS:
        raise MessageTooComplex("line count")
    if raw.count(b"\n--") + raw.count(b"\r--") > MAX_BOUNDARY_LINES:
        raise MessageTooComplex("boundary lines")
    if len(_BOUNDARY_DECLARATION.findall(raw)) > MAX_BOUNDARY_DECLARATIONS:
        raise MessageTooComplex("boundary declarations")


def _header_fields(header_block: bytes) -> list[bytes]:
    fields: list[bytes] = []
    for line in header_block.splitlines(keepends=True):
        if fields and line[:1] in (b" ", b"\t"):
            fields[-1] += line
        else:
            fields.append(line)
    return fields


def _verifiable_from(message: Message) -> str:
    values = [str(value) for key, value in message.raw_items() if key.lower() == "from"]
    return strict_address(values[0]) if len(values) == 1 else ""


def _walk_parts(message: Message) -> _Parts:
    text = ""
    html = ""
    attachments: list[ParsedAttachment] = []
    dropped = 0
    for seen, part in enumerate(_iter_leaf_parts(message)):
        if seen >= MAX_PARTS:
            dropped += 1
            continue
        content_type = part.get_content_type()
        is_attachment = part.get_content_disposition() == "attachment" or bool(part.get_filename())
        if not is_attachment and content_type == "text/plain" and not text:
            text = _decoded_text(part)
        elif not is_attachment and content_type == "text/html" and not html:
            html = _decoded_text(part)
        elif not is_attachment and content_type in ("text/plain", "text/html"):
            continue
        elif len(attachments) >= MAX_ATTACHMENTS:
            dropped += 1
        else:
            attachments.append(_attachment(len(attachments), part, content_type))
    return _Parts(text=text, html=html, attachments=attachments, dropped=dropped)


def _iter_leaf_parts(message: Message) -> list[Message]:
    """Depth-first, without recursion: a stranger chooses how deep the tree goes, and a message/rfc822 stays whole."""
    leaves: list[Message] = []
    stack: list[Message] = [message]
    while stack and len(leaves) <= MAX_PARTS:
        part = stack.pop()
        payload = part.get_payload()
        if part.is_multipart() and isinstance(payload, list) and part.get_content_maintype() == "multipart":
            stack.extend(reversed(payload))  # type: ignore[arg-type]
        else:
            leaves.append(part)
    return leaves


def _attachment(index: int, part: Message, content_type: str) -> ParsedAttachment:
    content = _decoded_bytes(part)
    content_id = _clean(_header(part, "content-id")).strip("<> ")
    return ParsedAttachment(
        index=index,
        filename=_safe_filename(part, index),
        content_type=content_type,
        size=len(content),
        content=content,
        content_id=content_id[:MAX_MESSAGE_ID_CHARS],
        inline=part.get_content_disposition() == "inline" or (bool(content_id) and not part.get_filename()),
    )


def _inline_images(html: str, attachments: list[ParsedAttachment]) -> str:
    if not html or "cid:" not in html.lower():
        return html
    by_content_id = {
        attachment.content_id: attachment
        for attachment in attachments
        if attachment.content_id
        and attachment.content_type in INLINE_IMAGE_TYPES
        and attachment.size <= MAX_INLINE_IMAGE_BYTES
    }
    budget = {"left": MAX_INLINE_IMAGES_BYTES}

    def replace(match: re.Match[str]) -> str:
        attachment = by_content_id.get(match.group(1))
        if attachment is None or attachment.size > budget["left"]:
            return match.group(0)
        budget["left"] -= attachment.size
        return f"data:{attachment.content_type};base64,{base64.b64encode(attachment.content).decode('ascii')}"

    return _CID_REFERENCE.sub(replace, html)


def _decoded_text(part: Message) -> str:
    try:
        content = part.get_content() if isinstance(part, EmailMessage) else None
        if isinstance(content, str):
            return _clean_body(content)
    except (LookupError, UnicodeError, ValueError, AssertionError):
        pass
    return _clean_body(_decoded_bytes(part).decode("utf-8", errors="replace"))


def _decoded_bytes(part: Message) -> bytes:
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload
    # A message/rfc822 attachment decodes to nothing, so its bytes come from serializing it again.
    try:
        return part.get_payload(0).as_bytes()  # type: ignore[union-attr]
    except (TypeError, IndexError, ValueError, AttributeError, UnicodeError, LookupError):
        return b""


def _safe_filename(part: Message, index: int) -> str:
    try:
        name = part.get_filename() or ""
    except (ValueError, LookupError, IndexError, AttributeError):
        name = ""
    name = _FILENAME_UNSAFE.sub("_", _encodable(name)).strip(" .")
    return name[-MAX_FILENAME_CHARS:] or f"attachment-{index + 1}"


def _headers(message: Message) -> tuple[ParsedHeader, ...]:
    headers: list[ParsedHeader] = []
    for name in message.keys()[:MAX_HEADERS]:
        headers.append(ParsedHeader(name=_clean(name)[:200], value=_clean(_raw_header(message, name))))
    return tuple(headers)


def _header(message: Message, name: str) -> str:
    """Header parsing raises on some malformed input, and a bad header must not cost the whole message."""
    try:
        return str(message.get(name, "") or "")
    except (ValueError, IndexError, AttributeError, LookupError, TypeError):
        return ""


def _unparsed_header(message: Message, name: str) -> str:
    """The parser cuts a Message-ID at a character it dislikes, and reply matching needs the sender's exact value."""
    for key, value in message.raw_items():
        if key.lower() == name:
            return str(value)
    return ""


def _raw_header(message: Message, name: str) -> str:
    try:
        return str(message.get(name, "") or "")[:MAX_HEADER_VALUE_CHARS]
    except (ValueError, IndexError, AttributeError, LookupError, TypeError):
        return ""


def _single_address(value: str) -> _Sender:
    name, address = parseaddr(_clean(value))
    return _Sender(name=name[:MAX_ADDRESS_CHARS], address=address.strip().lower()[:MAX_ADDRESS_CHARS])


def _addresses(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    parsed = getaddresses([_clean(value)])[:MAX_ADDRESSES]
    return tuple(address.strip().lower()[:MAX_ADDRESS_CHARS] for _, address in parsed if address.strip())


def _message_ids(value: str) -> tuple[str, ...]:
    return tuple(_MESSAGE_ID.findall(value)[-MAX_REFERENCES:])


def _bounded(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_BODY_CHARS:
        return value, False
    return value[:MAX_BODY_CHARS], True


def _clean(value: str) -> str:
    return _CONTROL_CHARS.sub("", _encodable(value)).replace("\r", " ").replace("\n", " ").strip()


def _clean_body(value: str) -> str:
    return _encodable(value).replace("\x00", "")


def _encodable(value: str) -> str:
    """Raw 8-bit header bytes reach Python as lone surrogates, which Postgres and object storage can't encode."""
    return value.encode("utf-8", errors="replace").decode("utf-8")
