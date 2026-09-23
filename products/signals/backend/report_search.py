"""Free-text search over inbox reports, shared by the report list filter and its tests."""

import re

from django.db.models import Exists, OuterRef, Q

from products.signals.backend.models import SignalReportArtefact

# A caller that pastes a whole sentence gets the first terms honored and the rest dropped, so one
# request can never fan out into an unbounded number of substring scans.
MAX_SEARCH_TERMS = 8

# Everything that is not a letter or a digit separates terms. This is what makes `$web_vitals`
# find a report titled "Web Vitals", and a report titled "$web_vitals" findable by "web vitals":
# both sides reduce to the same terms, so the punctuation an event name or an identifier carries
# stops deciding whether the report is found.
_TERM_SEPARATORS = re.compile(r"[^0-9A-Za-z]+")


def report_search_terms(search: str) -> list[str]:
    """Split a search string into the terms a report must match, in order, capped in count."""
    return [term for term in _TERM_SEPARATORS.split(search) if term][:MAX_SEARCH_TERMS]


def report_search_predicate(terms: list[str], evidence_report_ids: set[str]) -> Q:
    """Match a report whose own content holds every term, or whose evidence already matched.

    Terms are matched independently rather than as one phrase, because a caller searching for a
    report it has not read writes its own words — "Toronto registration" for a report titled
    "Registration drops for users in Toronto". A phrase match finds neither that report nor the
    duplicate the caller is about to file.

    A term may match the title, the summary, or a work-log note, and different terms may match
    different fields: the summary a research pass rewrote and the note a later pass appended
    describe the same report, so neither alone is the whole of what the report says.

    `evidence_report_ids` comes from ClickHouse (`fetch_report_ids_for_search_terms`) and already
    holds only reports matching every term, so it joins as an alternative to the Postgres match.
    """
    own_content = Q()
    for term in terms:
        notes_with_term = SignalReportArtefact.objects.filter(
            report=OuterRef("pk"),
            type=SignalReportArtefact.ArtefactType.NOTE,
            content__icontains=term,
        )
        own_content &= Q(title__icontains=term) | Q(summary__icontains=term) | Q(Exists(notes_with_term))
    if not evidence_report_ids:
        return own_content
    return own_content | Q(id__in=evidence_report_ids)
