import json
from collections.abc import Callable, Sequence
from datetime import datetime

from posthog.dataclasses import frozen

from products.signals.backend.facade import api as signals

from ..facade.enums import FigureSourceKind, FigureText
from .figures import Figure, is_zero, numbers_in, same_amount
from .jev import JevClient, JevPick
from .prose import plain_line, without_code_blocks
from .sentences import split_sentences
from .signal_text import SignalInput

FIGURE_MODEL = "posthog/hogference/jevk5-fp8-0.2"
KIND_THRESHOLD = 0.7
SOURCE_THRESHOLD = 0.6
RELATION_THRESHOLD = 0.6
UNNAMED_THRESHOLD = 0.75
_MAX_MARKS = 4
_MAX_CLAIMS = 12
_MAX_CANDIDATES = 6
_WINDOW = 200
_LETTERS = "ABCDEF"
_SOURCE_ORDER = {FigureSourceKind.SIGNAL: 0, FigureSourceKind.RESEARCH: 1}
_RESEARCH_FIELDS = {
    "priority_judgment": "explanation",
    "actionability_judgment": "explanation",
    "signal_finding": "data_queried",
    "check_scheduled": "rationale",
    "note": "note",
}
RESEARCH_TYPES = tuple(_RESEARCH_FIELDS)
_PLAN_HEADING = "verification plan"
_AUDIENCE_NOUNS = frozenset(
    "people person persons user users team teams customer customers organization organizations organisation "
    "organisations org orgs account accounts companies company project projects workspace workspaces session "
    "sessions visitor visitors member members".split()
)
KIND_QUESTION = "What does the number marked with [[ ]] in the claim describe?"
KIND_MEASURED = "measured result: a count, total, rate, share, amount of money or duration that was observed"
KIND_LABELS = [
    KIND_MEASURED,
    "date or time: a day, month, year or time of day",
    "identifier: an ID, version, ticket or issue number, or status code",
    "window length: the length of the period that a result covers",
    "limit or target: a value that is set, not observed",
    "other",
]
SOURCE_QUESTION = "Which source states the same result as the number marked with [[ ]] in the claim?"
SOURCE_NONE = "none: no source states this result"
RELATION_QUESTION = (
    "How does the number marked with [[ ]] in the source relate to the number marked with [[ ]] in the claim?"
)
RELATION_SAME = "same: the source number is the same result, about the same thing, group and period"
RELATION_LABELS = [
    RELATION_SAME,
    "different: the source number is about another thing, group or period",
    "unclear: the source does not say enough to tell",
]
NAMED_QUESTION = "Does this source sentence say what the number marked with [[ ]] counts?"
UNNAMED = "unnamed: a reader needs other sentences to know what the number counts"
NAMED = "named: the sentence alone says what the number counts"
NAMED_LABELS = [NAMED, UNNAMED]


@frozen
class ResearchNote:
    artefact_id: str
    text: str
    at: datetime


@frozen
class SourceSentence:
    kind: FigureSourceKind
    source_id: str
    sentence: str
    at: datetime


@frozen
class Candidate:
    source: SourceSentence
    number: Figure


@frozen
class FigureClaim:
    text_name: FigureText
    figure: Figure
    claim: str
    candidates: list[Candidate]


@frozen
class FigureMatch:
    claim: FigureClaim
    source: Candidate


def _content_dict(content: str) -> dict[str, object]:
    try:
        parsed = json.loads(content)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def research_notes(artefacts: Sequence[signals.ReportArtefactText]) -> list[ResearchNote]:
    notes: list[ResearchNote] = []
    for artefact in artefacts:
        field = _RESEARCH_FIELDS.get(artefact.type)
        value = _content_dict(artefact.content).get(field or "")
        text = value.strip() if isinstance(value, str) else ""
        if not text or text.lstrip("# ").lower().startswith(_PLAN_HEADING):
            continue
        notes.append(ResearchNote(artefact_id=artefact.artefact_id, text=text, at=artefact.created_at))
    return notes


def _sentences_of(text: str) -> list[str]:
    lines = [plain_line(line) for line in without_code_blocks(text).split("\n")]
    return [sentence.strip() for line in lines if line for _, sentence in split_sentences(line) if sentence.strip()]


def source_sentences(report_signals: Sequence[SignalInput], notes: Sequence[ResearchNote]) -> list[SourceSentence]:
    from_signals = [
        SourceSentence(kind=FigureSourceKind.SIGNAL, source_id=signal.signal_id, sentence=sentence, at=signal.timestamp)
        for signal in report_signals
        for sentence in _sentences_of(signal.content)
    ]
    from_notes = [
        SourceSentence(kind=FigureSourceKind.RESEARCH, source_id=note.artefact_id, sentence=sentence, at=note.at)
        for note in notes
        for sentence in _sentences_of(note.text)
    ]
    return [*from_signals, *from_notes]


def _with_mark(text: str, start: int, end: int) -> str:
    return f"{text[:start]}[[{text[start:end]}]]{text[end:]}"


def _claim_sentence(text: str, figure: Figure) -> str:
    for start, sentence in split_sentences(text):
        if start <= figure.start < start + len(sentence):
            return _with_mark(sentence, figure.start - start, figure.end - start).strip()
    return _with_mark(text, figure.start, figure.end)


def _candidates(figure: Figure, sources: list[SourceSentence]) -> list[Candidate]:
    seen: set[str] = set()
    candidates: list[Candidate] = []
    for source in sorted(sources, key=lambda source: _SOURCE_ORDER[source.kind]):
        if source.sentence in seen:
            continue
        seen.add(source.sentence)
        candidates.extend(
            Candidate(source=source, number=number)
            for number in numbers_in(source.sentence)
            if same_amount(figure.amount, number.amount)
        )
    return candidates[:_MAX_CANDIDATES]


def figure_claims(
    texts: dict[FigureText, str], sources: list[SourceSentence], prose: dict[FigureText, str]
) -> list[FigureClaim]:
    claims: list[FigureClaim] = []
    for name, text in texts.items():
        for figure in numbers_in(prose[name]):
            candidates = [] if is_zero(figure.amount) else _candidates(figure, sources)
            if candidates:
                claims.append(
                    FigureClaim(
                        text_name=name, figure=figure, claim=_claim_sentence(text, figure), candidates=candidates
                    )
                )
    return claims


def _window(candidate: Candidate) -> str:
    sentence, number = candidate.source.sentence, candidate.number
    start = max(0, number.start - _WINDOW)
    end = min(len(sentence), number.end + _WINDOW)
    if start > 0:
        space = sentence.find(" ", start, number.start)
        start = space + 1 if space >= 0 else start
    if end < len(sentence):
        space = sentence.rfind(" ", number.end, end)
        end = space if space >= 0 else end
    before = "…" if start > 0 else ""
    after = "…" if end < len(sentence) else ""
    return f"{before}{_with_mark(sentence[start:end], number.start - start, number.end - start)}{after}"


def kind_item(claim: FigureClaim) -> str:
    return f"Claim: {claim.claim}"


def source_item(claim: FigureClaim, ordered: Sequence[Candidate]) -> str:
    sources = [f"Source {letter}: {_window(candidate)}" for letter, candidate in zip(_LETTERS, ordered)]
    return "\n".join([f"Claim: {claim.claim}", "", *sources])


def source_labels(count: int) -> list[str]:
    return [*_LETTERS[:count], SOURCE_NONE]


def relation_item(claim: FigureClaim, candidate: Candidate) -> str:
    return f"Claim: {claim.claim}\n\nSource: {_window(candidate)}"


def named_item(candidate: Candidate) -> str:
    return f"Source: {_window(candidate)}"


def _orders(claim: FigureClaim) -> list[list[Candidate]]:
    return [list(claim.candidates), list(reversed(claim.candidates))]


def _sure(pick: JevPick | None, label: str, threshold: float) -> bool:
    return pick is not None and pick.label == label and pick.probability >= threshold


def _picked(claim: FigureClaim, ordered: list[Candidate], picks: dict[str, JevPick | None]) -> Candidate | None:
    pick = picks.get(source_item(claim, ordered))
    letters = _LETTERS[: len(ordered)]
    if pick is None or pick.probability < SOURCE_THRESHOLD or pick.label not in letters:
        return None
    return ordered[letters.index(pick.label)]


def _agreed_source(claim: FigureClaim, picks: dict[str, JevPick | None]) -> Candidate | None:
    forward, backward = (_picked(claim, ordered, picks) for ordered in _orders(claim))
    return forward if forward is not None and forward == backward else None


def _about_people(figure: Figure) -> bool:
    return (figure.noun or "").lower() in _AUDIENCE_NOUNS


def _people_first[T](items: list[T], figure: Callable[[T], Figure], limit: int) -> list[T]:
    order = sorted(range(len(items)), key=lambda index: (not _about_people(figure(items[index])), index))
    kept = set(order[:limit])
    return [item for index, item in enumerate(items) if index in kept]


def _picks(jev: JevClient, items: list[str], question: str, labels: list[str]) -> dict[str, JevPick | None]:
    unique = list(dict.fromkeys(items))
    return dict(zip(unique, jev.choice(unique, question, labels))) if unique else {}


def _source_picks(jev: JevClient, claims: list[FigureClaim]) -> dict[str, JevPick | None]:
    picks: dict[str, JevPick | None] = {}
    for count in sorted({len(claim.candidates) for claim in claims}):
        items = [
            source_item(claim, ordered)
            for claim in claims
            if len(claim.candidates) == count
            for ordered in _orders(claim)
        ]
        picks |= _picks(jev, items, SOURCE_QUESTION, source_labels(count))
    return picks


def match_figures(
    texts: dict[FigureText, str],
    report_signals: Sequence[SignalInput],
    notes: Sequence[ResearchNote],
    jev: JevClient,
    prose: dict[FigureText, str],
) -> list[FigureMatch]:
    sources = source_sentences(report_signals, notes)
    claims = _people_first(figure_claims(texts, sources, prose), lambda claim: claim.figure, _MAX_CLAIMS)
    kinds = _picks(jev, [kind_item(claim) for claim in claims], KIND_QUESTION, KIND_LABELS)
    measured = [claim for claim in claims if _sure(kinds.get(kind_item(claim)), KIND_MEASURED, KIND_THRESHOLD)]
    picks = _source_picks(jev, measured)
    agreed = [(claim, candidate) for claim in measured if (candidate := _agreed_source(claim, picks))]
    relation_items = [relation_item(claim, candidate) for claim, candidate in agreed]
    relations = _picks(jev, relation_items, RELATION_QUESTION, RELATION_LABELS)
    same = [
        (claim, candidate)
        for claim, candidate in agreed
        if _sure(relations.get(relation_item(claim, candidate)), RELATION_SAME, RELATION_THRESHOLD)
    ]
    named = _picks(jev, [named_item(candidate) for _, candidate in same], NAMED_QUESTION, NAMED_LABELS)
    matches = [
        FigureMatch(claim=claim, source=candidate)
        for claim, candidate in same
        # Jev's named answers sit near 0.5 even for clear sentences, so only a sure "unnamed" drops a mark.
        if not _sure(named.get(named_item(candidate)), UNNAMED, UNNAMED_THRESHOLD)
    ]
    return _people_first(matches, lambda match: match.claim.figure, _MAX_MARKS)
