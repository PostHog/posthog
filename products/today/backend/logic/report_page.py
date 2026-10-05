from markdown_it.token import Token

from posthog.models import Team

from products.signals.backend.facade import api as signals

from ..facade import contracts
from . import evidence, impact, samples
from .formats import digits_end, github_links, is_word_char
from .prose import concise_text
from .report_text import MARKDOWN

_PROPOSAL_CHARS = 260
_IMPACT_CHARS = 180
_PULL_REFERENCE = "PR #"


def _prose_outside_code(markdown: str) -> str:
    tokens: list[Token] = MARKDOWN.parseInline(markdown)
    return "".join(child.content for token in tokens for child in token.children or [] if child.type == "text")


def impact_sentence(impact: str | None) -> str:
    text = concise_text(impact, _IMPACT_CHARS)
    return text if any(char.isdigit() for char in _prose_outside_code(text)) else ""


def proposal(page: signals.ReportPageSource) -> str:
    fallback = page.action_prompts[0] if page.action_prompts else None
    return concise_text(page.sections.solution or fallback, _PROPOSAL_CHARS)


def _pull_reference_numbers(text: str) -> list[str]:
    numbers: list[str] = []
    index = text.find(_PULL_REFERENCE)
    while index >= 0:
        number_start = index + len(_PULL_REFERENCE)
        number_end = digits_end(text, number_start)
        starts_word = index == 0 or not is_word_char(text[index - 1])
        ends_word = number_end == len(text) or not is_word_char(text[number_end])
        if starts_word and ends_word and number_end > number_start:
            numbers.append(text[number_start:number_end])
            index = text.find(_PULL_REFERENCE, number_end)
        else:
            index = text.find(_PULL_REFERENCE, index + 1)
    return numbers


def _pull_requests_in(text: str | None, repo_slug: str | None) -> dict[str, str | None]:
    body = text or ""
    found: dict[str, str | None] = {
        number: f"https://github.com/{repo_slug}/pull/{number}" if repo_slug else None
        for number in _pull_reference_numbers(body)
    }
    found |= {link.number: body[link.start : link.end] for link in github_links(body, lambda link: link.kind == "pull")}
    return found


def _only_pull_request(text: str | None, repo_slug: str | None) -> contracts.PullRequestLink | None:
    found = _pull_requests_in(text, repo_slug)
    if len(found) != 1:
        return None
    [(number, url)] = found.items()
    return contracts.PullRequestLink(url=url, number=int(number)) if url else None


def report_page(page: signals.ReportPageSource) -> contracts.ReportPage:
    solution = page.sections.solution
    inputs = evidence.newest_first(page.signals)
    return contracts.ReportPage(
        lead=page.sections.lead,
        proposal=proposal(page),
        impact_sentence=impact_sentence(page.sections.impact),
        named_pull_request=_only_pull_request(solution, page.repo_slug)
        or _only_pull_request(page.summary, page.repo_slug),
        solution_names_pull_request=bool(_pull_requests_in(solution, page.repo_slug)),
        evidence=[evidence.signal_view(signal) for signal in evidence.pick_evidence(inputs)],
        source_count=evidence.distinct_evidence_count(inputs),
        impact_numbers=impact.impact_numbers(inputs),
        last_seen=impact.last_occurrence(inputs),
    )


def page_source(*, team: Team, report_id: str) -> signals.ReportPageSource | None:
    if not samples.is_sample_id(report_id):
        return signals.report_page_source(team=team, report_id=report_id)
    sample = samples.sample_report(report_id)
    return samples.sample_page_source(sample) if sample is not None else None
