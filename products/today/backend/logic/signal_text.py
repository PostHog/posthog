import re
from urllib.parse import urlsplit

from posthog.dataclasses import frozen

from products.signals.backend.facade import api as signals

from ..facade import contracts
from ..facade.enums import CitedSource
from .prose import first_sentence, plain_line, readable_excerpt, split_prose, without_code_blocks

_BOILERPLATE_LINES = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^new error tracking issue created\b",
        r"^this error tracking issue is experiencing a spike\b",
        r"^\(baseline:",
        r"^-{3,}$",
        r"^(exception|uuid|commit sha|feature|type|value|filename):",
        r"^anomaly investigation for alert\b",
        r"^verdict changed from\b",
        r"^insight:",
        r"^\[(info|warning|critical)\]",
    )
]
_REPO_FILE_ID = re.compile(r"^([\w.-]+/[\w.-]+):([^\s:]+)$", re.ASCII)
_SLACK_LINK = re.compile(r"https?://[\w.-]*slack\.com/\S+", re.IGNORECASE | re.ASCII)
_URL = re.compile(r"https?://\S+")
_QUOTE_MARK = re.compile(r"“|”|(?<=\s)[\"']|^[\"']|[\"'](?=[\s.,;:!?]|\Z)")
_TRAILING_PUNCTUATION = re.compile(r"[\s,;:–—-]+\Z")
_PULL = re.compile(r"pull", re.IGNORECASE)
_DANGLING_WORDS = frozenset(
    "a an the and or but so with to of in on for by at from as into via than that which who".split()
)
_HEADLINE_CHARS = 155
_MIN_CLAUSE_CHARS = 120
_LINK_POINTER_WORDS = 6
_DETAIL_ENDS = (".", "!", "?", ":", ")")
_SCOUT = "signals_scout"
TICKET_SOURCES = frozenset({"conversations", "zendesk"})
RECORDING_SOURCES = frozenset({"replay_vision", "session_replay"})
_SLACK_HOST = "slack.com"

SignalInput = signals.ReportSignal


@frozen
class SignalDetail:
    lead: str
    rest: str
    facts: list[str]


def text_of(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def js_number(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return str(int(value)) if float(value).is_integer() else str(value)


def _unclosed_quote_start(text: str) -> int:
    opened = -1
    for match in _QUOTE_MARK.finditer(text):
        index = match.start()
        mark = match.group(0)
        opening = mark == "“" or (mark != "”" and (index == 0 or text[index - 1].isspace()))
        opened = index if opening else -1
    return opened


def _without_dangling_words(text: str) -> str:
    words = text.split(" ")
    while len(words) > 1 and words[-1].lower() in _DANGLING_WORDS:
        words.pop()
    return " ".join(words)


def _fit_headline(text: str) -> str:
    if len(text) <= _HEADLINE_CHARS:
        return text
    window = text[:_HEADLINE_CHARS]
    clause = max(window.rfind(", "), window.rfind("; "))
    word_end = clause if clause >= _MIN_CLAUSE_CHARS else window.rfind(" ")
    cut = text[: word_end if word_end > 0 else _HEADLINE_CHARS]
    quote_start = _unclosed_quote_start(cut)
    body = cut[:quote_start] if quote_start > _MIN_CLAUSE_CHARS / 2 else cut
    trimmed = _TRAILING_PUNCTUATION.sub("", _without_dangling_words(_TRAILING_PUNCTUATION.sub("", body)))
    return f"{trimmed}…"


def _is_boilerplate(line: str) -> bool:
    return any(pattern.search(line) for pattern in _BOILERPLATE_LINES)


def headline(signal: SignalInput) -> str:
    for raw in without_code_blocks(signal.content).split("\n"):
        line = plain_line(raw)
        if line and not _is_boilerplate(line):
            return _fit_headline(readable_excerpt(first_sentence(line)))
    return _fit_headline(readable_excerpt(plain_line(signal.content))) or "Signal"


def _without_link_pointers(line: str) -> str:
    def keeps(sentence: str) -> bool:
        rest = _URL.sub("", sentence).strip()
        return rest == sentence.strip() or len(rest.split()) > _LINK_POINTER_WORDS

    return " ".join(sentence for sentence in split_prose(line) if keeps(sentence))


def is_pull_request(signal: SignalInput) -> bool:
    pull_request = signal.extra.get("pull_request")
    pull_request_object = "pull_request" in signal.extra and (
        pull_request is None or isinstance(pull_request, dict | list)
    )
    return bool(_PULL.search(signal.source_type)) or pull_request_object or "merged_at" in signal.extra


def code_file(signal: SignalInput) -> contracts.CodeFile | None:
    match = _REPO_FILE_ID.match(signal.source_id) if signal.source_product == _SCOUT else None
    return contracts.CodeFile(repo=match.group(1), path=match.group(2)) if match else None


def github_file_url(file: contracts.CodeFile) -> str:
    return f"https://github.com/{file.repo}/blob/HEAD/{file.path}"


def _is_slack_host(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host == _SLACK_HOST or host.endswith(f".{_SLACK_HOST}")


def slack_thread(signal: SignalInput) -> str | None:
    match = _SLACK_LINK.search(signal.content) if signal.source_product == _SCOUT else None
    url = safe_http_url(match.group(0).rstrip(").,")) if match else None
    return url if url and _is_slack_host(url) else None


def safe_http_url(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return url if parts.scheme in ("http", "https") and parts.netloc else None


def cited_source(signal: SignalInput) -> CitedSource | None:
    if code_file(signal):
        return CitedSource.CODE
    return CitedSource.SLACK if slack_thread(signal) else None


def _meta_parts(signal: SignalInput) -> list[str]:
    if signal.source_product == "github":
        number = js_number(signal.extra.get("number"))
        kind = "Pull request" if is_pull_request(signal) else "Issue"
        return [f"{kind} #{number}"] if number else []
    if signal.source_product in TICKET_SOURCES:
        ticket = js_number(signal.extra.get("ticket_number"))
        return [f"Ticket #{ticket}"] if ticket else []
    if signal.source_product == _SCOUT:
        file = code_file(signal)
        return [file.path.split("/")[-1]] if file else []
    return []


def meta(signal: SignalInput) -> str:
    return " · ".join(_meta_parts(signal))


def _pganalyze_facts(signal: SignalInput) -> list[str]:
    if signal.source_product != "pganalyze":
        return []
    severity = text_of(signal.extra.get("severity"))
    server = text_of(signal.extra.get("server_name"))
    return [fact for fact in (server, f"{severity} severity" if severity else None) if fact]


def detail(signal: SignalInput) -> SignalDetail:
    lines = [plain_line(_without_link_pointers(line)) for line in without_code_blocks(signal.content).split("\n")]
    kept = [line for line in lines if line and not _is_boilerplate(line)]
    text = " ".join(line if line.endswith(_DETAIL_ENDS) else f"{line}." for line in kept)
    lead = first_sentence(text)
    return SignalDetail(
        lead=readable_excerpt(lead or plain_line(signal.content)),
        rest=readable_excerpt(text[len(lead) :].strip()),
        facts=[*_pganalyze_facts(signal), *_meta_parts(signal)],
    )
