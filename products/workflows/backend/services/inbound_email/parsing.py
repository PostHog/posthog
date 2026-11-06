"""Turns raw MIME from a stranger into bounded, plain data. Everything read here is attacker-controlled."""

import re
import email
import base64
import email.policy
from email.message import EmailMessage, Message
from email.utils import getaddresses, parseaddr

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

MAX_REFERENCES = 50
_MESSAGE_ID = re.compile(r"<[^<>\s]{1,500}>")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
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


def parse_email(raw: bytes) -> ParsedEmail:
    message = email.message_from_bytes(raw, policy=email.policy.default)
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
        references=_message_ids(_unparsed_header(message, "references")),
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
    )


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


def scrub_recipient_trace_headers(raw: bytes) -> bytes:
    """Remove the headers that could name another team's envelope recipients from one team's copy of a message."""
    separator = re.search(rb"\r?\n\r?\n", raw)
    header_block, rest = (raw[: separator.start()], raw[separator.start() :]) if separator else (raw, b"")
    kept: list[bytes] = []
    dropping = False
    for line in header_block.splitlines(keepends=True):
        if line[:1] in (b" ", b"\t"):
            if not dropping:
                kept.append(line)
            continue
        name = line.partition(b":")[0].strip().lower().decode("ascii", errors="replace")
        dropping = name in RECIPIENT_TRACE_HEADERS or name.startswith("x-ses-")
        if not dropping:
            kept.append(line)
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
    name = _FILENAME_UNSAFE.sub("_", name).strip(" .")
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
    return _CONTROL_CHARS.sub("", value).replace("\r", " ").replace("\n", " ").strip()


def _clean_body(value: str) -> str:
    return value.replace("\x00", "")
