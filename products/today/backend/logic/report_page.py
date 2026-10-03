import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

from posthog.models import Team

from products.signals.backend.facade import api as signals

from ..facade import contracts
from . import evidence, impact, samples
from .prose import concise_text

_PROPOSAL_CHARS = 260
_IMPACT_CHARS = 180
_ACTION_CAPABLE_STATUSES = frozenset({"ready", "pending_input"})
_MARKDOWN = MarkdownIt("commonmark")
_GITHUB_PULL_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)", re.ASCII)
_PULL_REFERENCE = re.compile(r"\bPR #(\d+)\b", re.ASCII)


def _code_spans(markdown: str) -> list[str]:
    tokens: list[Token] = _MARKDOWN.parseInline(markdown)
    return [child.content for token in tokens for child in token.children or [] if child.type == "code_inline"]


def _names_code_path(markdown: str) -> bool:
    return any("/" in span or "." in span for span in _code_spans(markdown))


def impact_sentence(impact: str | None) -> str:
    text = concise_text(impact, _IMPACT_CHARS)
    states_measurement = any(char.isdigit() for char in text) and not _names_code_path(text)
    return text if states_measurement else ""


def _action_capable(page: signals.ReportPageSource) -> bool:
    return (
        page.status in _ACTION_CAPABLE_STATUSES
        and page.already_addressed is not True
        and page.actionability != "not_actionable"
        and not page.has_pull_requests
    )


def proposal(page: signals.ReportPageSource) -> str:
    fallback = page.suggested_prompts[0] if page.suggested_prompts and _action_capable(page) else None
    return concise_text(page.sections.solution or fallback, _PROPOSAL_CHARS)


def _pull_requests_in(text: str | None, repo_slug: str | None) -> dict[str, str]:
    found = {match.group(1): match.group(0) for match in _GITHUB_PULL_URL.finditer(text or "")}
    if found or not repo_slug:
        return found
    return {
        match.group(1): f"https://github.com/{repo_slug}/pull/{match.group(1)}"
        for match in _PULL_REFERENCE.finditer(text or "")
    }


def _only_pull_request(text: str | None, repo_slug: str | None) -> contracts.PullRequestLink | None:
    found = _pull_requests_in(text, repo_slug)
    if len(found) != 1:
        return None
    [(number, url)] = found.items()
    return contracts.PullRequestLink(url=url, number=int(number))


def _signal_input(signal: signals.ReportSignal) -> evidence.SignalInput:
    return evidence.SignalInput(
        signal_id=signal.signal_id,
        content=signal.content,
        source_product=signal.source_product,
        source_type=signal.source_type,
        source_id=signal.source_id,
        timestamp=signal.timestamp,
        extra=signal.extra,
    )


def report_page(page: signals.ReportPageSource) -> contracts.ReportPage:
    solution = page.sections.solution
    inputs = evidence.newest_first([_signal_input(signal) for signal in page.signals])
    return contracts.ReportPage(
        lead=page.sections.lead,
        proposal=proposal(page),
        impact_sentence=impact_sentence(page.sections.impact),
        in_flight_pull_request=_only_pull_request(solution, page.repo_slug)
        or _only_pull_request(page.summary, page.repo_slug),
        solution_names_pull_request=bool(_pull_requests_in(solution, page.repo_slug)),
        signals=[evidence.signal_view(signal) for signal in inputs],
        evidence=[signal.signal_id for signal in evidence.pick_evidence(inputs)],
        evidence_count=evidence.distinct_evidence_count(inputs),
        impact_numbers=impact.impact_numbers(inputs),
        last_seen=impact.last_occurrence(inputs),
    )


def page_source(*, team: Team, report_id: str) -> signals.ReportPageSource | None:
    if not samples.is_sample_id(report_id):
        return signals.report_page_source(team=team, report_id=report_id)
    sample = samples.sample_report(report_id)
    return samples.sample_page_source(sample) if sample is not None else None
