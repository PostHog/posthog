import re
from collections.abc import Sequence
from dataclasses import replace
from itertools import accumulate

from posthog.dataclasses import frozen

from ..facade import contracts
from ..facade.enums import KeyClauseRole
from .formats import utf16_offset
from .jev import JevClient, JevPick
from .prose import block_lines
from .report_text import rendered_text
from .sentences import split_sentences

_WORD = re.compile(r"[^\W_](?:\w|(?<=[^\W_])['’.](?=[^\W_])|(?<=\d)[,;](?=\d))*|_+\w*")
_IN_PHRASE = set("'’‘-./_\"“”`$€£%#@*+=")
_DASHES = set("–—")
_CLAUSE_OPENERS = frozenset(
    "because since so but and or which while when after until unless although though whereas".split()
)
_MIN_SIDE_WORDS = 3
_MIN_CLAUSE_WORDS = 2
_MAX_CLAUSES = 15
_MIN_ROLE_PROBABILITY = 0.75
_MAX_KEY_CLAUSE_WORDS = 16
_MIN_SENTENCE_WORDS = 6
_MAX_REPORT_SENTENCES = 25
_MAX_EXPANSION_SENTENCES = 2
_MIN_EXPANSION_PROBABILITY = 0.6
_MIN_SECOND_EXPANSION_PROBABILITY = 0.75
_MAX_KEY_CLAUSES = 2
_CANDIDATES_PER_ROLE = 2
_EXPANSION_QUESTION = "Answer true if the sentence explains the marked part in more detail."
_ROLE_LABELS = ["problem", "cause", "fix", "detail"]
_ROLE_QUESTION = (
    "What does this part tell the reader? problem: what goes wrong or who is hurt. cause: why it happens. "
    "fix: what to change. detail: anything else, such as numbers, background, tests, or follow-ups."
)


@frozen
class KeyClauseRequest:
    text: str
    roles: list[KeyClauseRole]


@frozen
class Clause:
    start: int
    end: int
    text: str
    words: int


@frozen
class _ScoredClause:
    start: int
    end: int
    text: str
    role: KeyClauseRole
    confidence: float
    expansion: list[str]


@frozen
class _Word:
    start: int
    end: int
    text: str


def _joins_words(sentence: str, index: int) -> bool:
    char = sentence[index]
    before = sentence[index - 1] if index > 0 else " "
    after = sentence[index + 1] if index + 1 < len(sentence) else " "
    return char in _IN_PHRASE or (char in _DASHES and not before.isspace() and not after.isspace())


def _has_break(sentence: str, start: int, end: int) -> bool:
    return any(not sentence[index].isspace() and not _joins_words(sentence, index) for index in range(start, end))


def _word_runs(sentence: str, offset: int) -> list[list[_Word]]:
    runs: list[list[_Word]] = [[]]
    last = 0
    for match in _WORD.finditer(sentence):
        if _has_break(sentence, last, match.start()):
            runs.append([])
        runs[-1].append(_Word(start=offset + match.start(), end=offset + match.end(), text=match.group(0)))
        last = match.end()
    return runs


def _split_at_openers(run: list[_Word]) -> list[list[_Word]]:
    parts: list[list[_Word]] = [[]]
    for index, word in enumerate(run):
        both_sides_long = len(parts[-1]) >= _MIN_SIDE_WORDS and len(run) - index >= _MIN_SIDE_WORDS
        if word.text in _CLAUSE_OPENERS and both_sides_long:
            parts.append([])
        parts[-1].append(word)
    return parts


def _clause(text: str, words: list[_Word]) -> Clause:
    start, end = words[0].start, words[-1].end
    return Clause(start=start, end=end, text=text[start:end], words=len(words))


def text_clauses(text: str) -> list[Clause]:
    parts = [
        part
        for sentence_start, sentence in split_sentences(text)
        for run in _word_runs(sentence, sentence_start)
        for part in _split_at_openers(run)
    ]
    return [_clause(text, words) for words in parts if len(words) >= _MIN_CLAUSE_WORDS][:_MAX_CLAUSES]


def _clause_role_input(text: str, clause: Clause) -> str:
    return f"Text:\n{text}\n\nPart of the text:\n{clause.text}"


def _is_sure_role(pick: JevPick, role: KeyClauseRole, clause: Clause) -> bool:
    return pick.label == role and pick.probability >= _MIN_ROLE_PROBABILITY and clause.words <= _MAX_KEY_CLAUSE_WORDS


def _surest_clauses(clauses: list[Clause], picks: list[JevPick | None], role: KeyClauseRole) -> list[_ScoredClause]:
    sure = [
        (pick, clause) for clause, pick in zip(clauses, picks) if pick is not None and _is_sure_role(pick, role, clause)
    ]
    sure.sort(key=lambda candidate: -candidate[0].probability)
    return [
        _ScoredClause(
            start=clause.start, end=clause.end, text=clause.text, role=role, confidence=pick.probability, expansion=[]
        )
        for pick, clause in sure[:_CANDIDATES_PER_ROLE]
    ]


def _key_clauses(clauses: list[Clause], roles: list[KeyClauseRole], picks: list[JevPick | None]) -> list[_ScoredClause]:
    chosen = [key_clause for role in roles for key_clause in _surest_clauses(clauses, picks, role)]
    return sorted(chosen, key=lambda key_clause: key_clause.start)


def _chunked[T](values: Sequence[T], sizes: list[int]) -> list[list[T]]:
    edges = list(accumulate(sizes, initial=0))
    return [list(values[start:end]) for start, end in zip(edges, edges[1:])]


def _word_count(text: str) -> int:
    return len(_WORD.findall(text))


def _report_sentences(summary: str, shown: list[str]) -> list[str]:
    seen = {text.strip() for text in shown}
    sentences: list[str] = []
    for line in block_lines(summary):
        text = rendered_text(line).strip()
        if not text or text in seen:
            continue
        for _, sentence in split_sentences(text):
            value = sentence.strip()
            already_read = any(value in part for part in shown) or value in sentences
            if _word_count(value) >= _MIN_SENTENCE_WORDS and not already_read:
                sentences.append(value)
    return sentences[:_MAX_REPORT_SENTENCES]


def _expansion_input(key_clause: _ScoredClause, sentence: str) -> str:
    return f"Marked part:\n{key_clause.text}\n\nSentence from the report:\n{sentence}"


def _expansion_for(sentences: list[str], probabilities: Sequence[float | None]) -> list[str]:
    likely = sorted(
        (
            (probability, index)
            for index, probability in zip(range(len(sentences)), probabilities)
            if probability is not None and probability >= _MIN_EXPANSION_PROBABILITY
        ),
        key=lambda candidate: -candidate[0],
    )
    kept = [
        index
        for rank, (probability, index) in enumerate(likely)
        if rank == 0 or probability >= _MIN_SECOND_EXPANSION_PROBABILITY
    ]
    return [sentences[index] for index in sorted(kept[:_MAX_EXPANSION_SENTENCES])]


def _best_explained(key_clauses: list[_ScoredClause]) -> list[_ScoredClause]:
    best: dict[KeyClauseRole, _ScoredClause] = {}
    for key_clause in key_clauses:
        current = best.get(key_clause.role)
        if key_clause.expansion and (current is None or key_clause.confidence > current.confidence):
            best[key_clause.role] = key_clause
    return sorted(best.values(), key=lambda key_clause: key_clause.start)


def _contract(text: str, key_clause: _ScoredClause) -> contracts.KeyClause:
    return contracts.KeyClause(
        start=utf16_offset(text, key_clause.start),
        end=utf16_offset(text, key_clause.end),
        role=key_clause.role,
        expansion=key_clause.expansion,
    )


def find_key_clauses(requests: list[KeyClauseRequest], summary: str, jev: JevClient) -> list[list[contracts.KeyClause]]:
    sentences = _report_sentences(summary, [request.text for request in requests])
    if not sentences:
        return [[] for _ in requests]
    clauses = [text_clauses(request.text) for request in requests]
    picks = jev.choice(
        [_clause_role_input(request.text, clause) for request, own in zip(requests, clauses) for clause in own],
        _ROLE_QUESTION,
        _ROLE_LABELS,
    )
    picked = [
        _key_clauses(own, request.roles, own_picks)
        for request, own, own_picks in zip(requests, clauses, _chunked(picks, [len(own) for own in clauses]))
    ]
    flat = [key_clause for own in picked for key_clause in own]
    answers = jev.yes_probability(
        [_expansion_input(key_clause, sentence) for key_clause in flat for sentence in sentences],
        _EXPANSION_QUESTION,
    )
    expanded = [
        replace(key_clause, expansion=_expansion_for(sentences, own_answers))
        for key_clause, own_answers in zip(flat, _chunked(answers, [len(sentences)] * len(flat)))
    ]
    best = [_best_explained(own) for own in _chunked(expanded, [len(own) for own in picked])]
    shown = sorted((key_clause for own in best for key_clause in own), key=lambda k: -k.confidence)[:_MAX_KEY_CLAUSES]
    return [
        [_contract(request.text, key_clause) for key_clause in own if key_clause in shown]
        for request, own in zip(requests, best)
    ]
