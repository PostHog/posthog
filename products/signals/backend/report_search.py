"""Free-text search over inbox reports, shared by the report list filter and its tests."""

import re
import unicodedata
from collections.abc import Mapping

from django.db.models import Exists, F, Func, OuterRef, Q, TextField, Value

from products.signals.backend.models import SignalReportArtefact

# A caller that pastes a whole sentence gets the first terms honored and the rest dropped, so one
# request can never fan out into an unbounded number of substring scans.
MAX_SEARCH_TERMS = 8

# Everything that is not a letter or a digit separates terms. This is what makes `$web_vitals`
# find a report titled "Web Vitals", and a report titled "$web_vitals" findable by "web vitals":
# both sides reduce to the same terms, so the punctuation an event name or an identifier carries
# stops deciding whether the report is found. "Letter" means any letter, so an accented word stays
# one term instead of fragments that match almost anything. The underscore is listed on its own
# because `\W` counts it as a letter, and it is a LIKE wildcard that must not reach a term.
_TERM_SEPARATORS = re.compile(r"[\W_]+")

# One Latin letter on its own is what a possessive or a contraction leaves behind once the
# apostrophe separates the word: "Toronto's" gives "Toronto" and "s". Every term has to match, so
# that fragment adds a condition the caller never asked for, and it excludes any report that
# happens to hold no "s". A single digit or a single character of a script that writes words in
# one character is a term the caller meant, so only the Latin letter is dropped.
_SINGLE_LATIN_LETTER = re.compile(r"[A-Za-z]")

# The text of a work-log note, read out of the serialized object it is stored in. Postgres 15 has
# no error-tolerant JSON parse, and casting to jsonb raises on a row that is not valid JSON, which
# fails the whole list request. A regex never raises: it returns null for a row it cannot read, so
# that row stops being searchable instead of taking the search down with it. Escapes stay escaped
# in what this returns, which cannot affect a match, because a term holds only letters and digits.
_NOTE_TEXT_PATTERN = r'"note"\s*:\s*"((?:[^"\\]|\\.)*)"'


def report_search_terms(search: str) -> list[str]:
    """Split a search string into the terms a report must match, in order, capped in count."""
    # An accent can arrive as one character or as a letter followed by a combining mark, and the
    # combining mark is not a letter, so the second spelling splits "Müller" into "Mu" and "ller".
    # Composing first makes both spellings one term, and matches the composed form that the
    # reports themselves are written in.
    composed = unicodedata.normalize("NFC", search)
    terms = [term for term in _TERM_SEPARATORS.split(composed) if term and not _SINGLE_LATIN_LETTER.fullmatch(term)]
    return terms[:MAX_SEARCH_TERMS]


def report_search_predicate(terms: list[str], evidence_report_ids_by_term: Mapping[str, set[str]]) -> Q:
    """Match a report that holds every term, in its own content or in its evidence.

    Terms match independently rather than as one phrase, because a caller searching for a report
    it has not read writes its own words: "Toronto registration" for a report titled "Registration
    drops for users in Toronto".

    A term may match the title, the summary, a work-log note, or the report's evidence, and
    different terms may match different ones. A research pass rewrites the summary, so what an
    earlier pass found can live on only in the work log, and an identifier the emitter recorded
    often reaches no further than the evidence. Each term is matched across both stores before the
    terms are combined, so one remembered word and one evidence-only identifier find the report
    between them.

    A note is stored as a serialized object, so only the note text is matched: the key names
    around it are not something the caller can read on the report.

    `evidence_report_ids_by_term` comes from ClickHouse (`fetch_report_ids_by_search_term`). A term
    missing from it has no evidence match, which is how the degraded lookup narrows the search to
    the report's own content instead of failing it.
    """
    note_text = Func(
        F("content"),
        Value(_NOTE_TEXT_PATTERN),
        function="substring",
        output_field=TextField(),
    )
    predicate = Q()
    for term in terms:
        notes_with_term = (
            SignalReportArtefact.objects.filter(
                report=OuterRef("pk"),
                type=SignalReportArtefact.ArtefactType.NOTE,
            )
            .annotate(note_text=note_text)
            .filter(note_text__icontains=term)
        )
        matches_term = Q(title__icontains=term) | Q(summary__icontains=term) | Q(Exists(notes_with_term))
        if evidence_ids := evidence_report_ids_by_term.get(term):
            matches_term |= Q(id__in=evidence_ids)
        predicate &= matches_term
    return predicate
