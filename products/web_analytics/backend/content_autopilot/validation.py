import re
import json
from typing import Any
from urllib.parse import ParseResult, urlparse

from posthog.dataclasses import frozen

from products.web_analytics.backend.content_autopilot.research import ResearchBundle
from products.web_analytics.backend.content_autopilot.site_discovery import site_host

MIN_WORDS = 250
LENGTH_TOLERANCE = 1.5
OVERLAP_WINDOW_CHARS = 40
MAX_REPORTED_ITEMS = 5

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_WORD_RE = re.compile(r"\S+")
STRUCTURED_DATA_TYPES = frozenset({"Article", "FAQPage"})


@frozen
class ValidationCheck:
    check_key: str
    label: str
    passed: bool
    message: str
    blocking: bool
    details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_key": self.check_key,
            "label": self.label,
            "passed": self.passed,
            "message": self.message,
            "blocking": self.blocking,
        }


@frozen
class JudgeVerdict:
    unsupported_claims: tuple[str, ...]
    answers_prompt: bool
    answers_prompt_reason: str
    brand_rule_violations: tuple[str, ...]


def _normalize_path(path: str) -> str:
    stripped = path.split("#", 1)[0].split("?", 1)[0].removesuffix(".md").rstrip("/")
    return stripped or "/"


def _parse(url: str) -> ParseResult | None:
    try:
        return urlparse(url)
    except ValueError:
        return None


def _url_path(url: str) -> str:
    parsed = _parse(url)
    return _normalize_path(parsed.path if parsed else url)


def _has_host(url: str) -> bool:
    parsed = _parse(url)
    return bool(parsed and parsed.netloc)


def _summarize(items: list[str]) -> str:
    shown = ", ".join(f"`{item[:120]}`" for item in items[:MAX_REPORTED_ITEMS])
    extra = len(items) - MAX_REPORTED_ITEMS
    return f"{shown} and {extra} more" if extra > 0 else shown


def word_count(markdown: str) -> int:
    return len(_WORD_RE.findall(markdown))


@frozen
class _StructureProblem:
    severity: int
    message: str


def _structure_problems(markdown: str) -> dict[str, _StructureProblem]:
    lines = markdown.splitlines()
    h1_count = sum(1 for line in lines if line.startswith("# "))
    words = word_count(markdown)
    problems: dict[str, _StructureProblem] = {}
    if h1_count != 1:
        problems["h1"] = _StructureProblem(
            severity=abs(h1_count - 1), message=f"it has {h1_count} H1 headings instead of one"
        )
    if not any(line.startswith("## ") for line in lines):
        problems["h2"] = _StructureProblem(severity=1, message="it has no H2 sections")
    if words < MIN_WORDS:
        problems["words"] = _StructureProblem(
            severity=MIN_WORDS - words, message=f"it has {words} words, fewer than {MIN_WORDS}"
        )
    if markdown.lstrip().startswith("---"):
        problems["frontmatter"] = _StructureProblem(
            severity=1, message="it starts with frontmatter, which belongs in the content package"
        )
    return problems


def check_structure(markdown: str, *, baseline: str | None = None) -> ValidationCheck:
    problems = _structure_problems(markdown)
    if baseline is not None:
        existing = _structure_problems(baseline)
        problems = {
            key: problem
            for key, problem in problems.items()
            if key not in existing or problem.severity > existing[key].severity
        }
    return ValidationCheck(
        check_key="structure",
        label="Page structure",
        passed=not problems,
        message="One H1, question-led sections, and enough depth."
        if not problems
        else f"Fix the page: {'; '.join(problem.message for problem in problems.values())}.",
        blocking=True,
    )


def check_length(markdown: str, *, budget: int) -> ValidationCheck:
    words = word_count(markdown)
    if words <= budget:
        message = f"{words} new words, within the budget of about {budget}."
    elif words <= budget * LENGTH_TOLERANCE:
        message = f"{words} new words, a little over the budget of about {budget}."
    else:
        message = f"{words} new words, well over the budget of about {budget}. Trim it before publishing."
    return ValidationCheck(
        check_key="length",
        label="Length",
        passed=words <= budget * LENGTH_TOLERANCE,
        message=message,
        blocking=False,
    )


def check_edit_placement(unplaced: tuple[str, ...]) -> ValidationCheck:
    return ValidationCheck(
        check_key="edit_placement",
        label="Edit placement",
        passed=not unplaced,
        message="Every edit landed where it was meant to."
        if not unplaced
        else f"These headings aren't on the page, so their edits were added at the end: {_summarize(list(unplaced))}.",
        blocking=False,
    )


def check_internal_links(markdown: str, *, site_origin: str, site_urls: list[str]) -> ValidationCheck:
    if not site_urls:
        return ValidationCheck(
            check_key="internal_links",
            label="Internal links",
            passed=True,
            message="The sitemap couldn't be read, so links weren't checked. Review them by hand.",
            blocking=False,
        )
    host = site_host(site_origin)
    known_paths = {_url_path(url) for url in site_urls}
    broken: list[str] = []
    for target in LINK_RE.findall(markdown):
        parsed = _parse(target)
        if parsed is None:
            broken.append(target)
            continue
        if parsed.netloc:
            absolute = target if parsed.scheme else f"https:{target}"
            if parsed.scheme not in {"", "http", "https"} or site_host(absolute) != host:
                continue
        elif not target.startswith("/"):
            continue
        if _normalize_path(parsed.path) not in known_paths:
            broken.append(target)
    return ValidationCheck(
        check_key="internal_links",
        label="Internal links",
        passed=not broken,
        message="Every internal link points to a page in the sitemap."
        if not broken
        else f"These links don't match a page in the sitemap: {_summarize(broken)}.",
        blocking=True,
    )


def _normalized_text(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def _windows(text: str) -> set[str]:
    windows: set[str] = set()
    start = 0
    while start + OVERLAP_WINDOW_CHARS <= len(text):
        windows.add(text[start : start + OVERLAP_WINDOW_CHARS])
        next_space = text.find(" ", start + 1)
        if next_space == -1:
            break
        start = next_space + 1
    return windows


def check_competitor_overlap(markdown: str, research: ResearchBundle) -> ValidationCheck:
    competitor_windows: set[str] = set()
    for document in research.competitor_documents:
        competitor_windows |= _windows(_normalized_text(document.text))
    copied = sorted(_windows(_normalized_text(markdown)) & competitor_windows)
    return ValidationCheck(
        check_key="originality",
        label="Originality",
        passed=not copied,
        message="No passages match the cited competitor pages."
        if not copied
        else f"Some passages match cited competitor pages word for word: {_summarize(copied)}.",
        blocking=True,
    )


def _has_expected_json_ld(document: dict[str, Any]) -> bool:
    declared = document.get("@type")
    types = (
        {declared} if isinstance(declared, str) else set(map(str, declared)) if isinstance(declared, list) else set()
    )
    if not document.get("@context") or not types & STRUCTURED_DATA_TYPES:
        return False
    return bool(document.get("mainEntity") if "FAQPage" in types else document.get("headline"))


def check_structured_data(json_ld: str) -> ValidationCheck:
    label = "Structured data"
    if not json_ld.strip():
        return ValidationCheck(
            check_key="structured_data",
            label=label,
            passed=False,
            message="No JSON-LD was produced. Answer engines use it to understand FAQ content.",
            blocking=False,
        )
    try:
        parsed = json.loads(json_ld)
    except json.JSONDecodeError:
        return ValidationCheck(
            check_key="structured_data",
            label=label,
            passed=False,
            message="The JSON-LD isn't valid JSON.",
            blocking=True,
        )
    valid = isinstance(parsed, dict) and _has_expected_json_ld(parsed)
    return ValidationCheck(
        check_key="structured_data",
        label=label,
        passed=valid,
        message="The JSON-LD is valid."
        if valid
        else "The JSON-LD needs an @context and an @type of FAQPage with questions, or Article with a headline.",
        blocking=True,
    )


def check_url_available(url_path: str, *, is_new_page: bool, site_urls: list[str]) -> ValidationCheck:
    if not is_new_page:
        return ValidationCheck(
            check_key="url", label="Page URL", passed=True, message="This updates an existing page.", blocking=True
        )
    segments = url_path.split("?", 1)[0].split("#", 1)[0].split("/")
    well_formed = (
        url_path.startswith("/") and not url_path.startswith("//") and "." not in segments and ".." not in segments
    )
    if not well_formed:
        return ValidationCheck(
            check_key="url",
            label="Page URL",
            passed=False,
            message=f"`{url_path[:200]}` isn't a root-relative path. Use a path like `/docs/new-page`.",
            blocking=True,
        )
    if not site_urls:
        return ValidationCheck(
            check_key="url",
            label="Page URL",
            passed=True,
            message=f"The sitemap couldn't be read, so check that `{url_path}` isn't already a page.",
            blocking=True,
        )
    taken = _normalize_path(url_path) in {_url_path(url) for url in site_urls}
    return ValidationCheck(
        check_key="url",
        label="Page URL",
        passed=not taken,
        message=f"`{url_path[:200]}` is already a page on the site." if taken else f"`{url_path}` is free to use.",
        blocking=True,
    )


def _page_key(url: str) -> str:
    return f"{site_host(url)}{_url_path(url)}"


def check_ledger_sources(
    source_ledger: list[dict[str, str]],
    research: ResearchBundle,
    *,
    competitor_ledger: list[dict[str, str]] | tuple[dict[str, str], ...] = (),
) -> ValidationCheck:
    site_paths = {_url_path(document.url) for document in research.site_documents}
    site_pages = {_page_key(document.url) for document in research.site_documents}
    researched_pages = {_page_key(document.url) for document in research.documents}
    site_sources = [entry["source_url"] for entry in source_ledger]
    competitor_sources = [entry["source_url"] for entry in competitor_ledger]
    outside = [
        url
        for url in site_sources
        if (_page_key(url) not in site_pages if _has_host(url) else _url_path(url) not in site_paths)
    ]
    outside += [url for url in competitor_sources if _page_key(url) not in researched_pages]
    return ValidationCheck(
        check_key="sources",
        label="Sources",
        passed=not outside,
        message="Every sourced claim cites a page that was part of the research."
        if not outside
        else f"Some claims cite pages that weren't part of the research: {_summarize(outside)}.",
        blocking=True,
    )


def judge_checks(verdict: JudgeVerdict, *, has_brand_rules: bool) -> list[ValidationCheck]:
    checks = [
        ValidationCheck(
            check_key="grounding",
            label="Sourced facts",
            passed=not verdict.unsupported_claims,
            message="Every claim is backed by the site's pages or by the other company's own pages."
            if not verdict.unsupported_claims
            else f"These claims aren't backed by a source: {_summarize(list(verdict.unsupported_claims))}.",
            blocking=True,
            details=verdict.unsupported_claims,
        ),
        ValidationCheck(
            check_key="intent",
            label="Answers the question",
            passed=verdict.answers_prompt,
            message=verdict.answers_prompt_reason[:500] or "Checked against the question.",
            blocking=True,
        ),
    ]
    if has_brand_rules:
        checks.append(
            ValidationCheck(
                check_key="brand",
                label="Brand rules",
                passed=not verdict.brand_rule_violations,
                message="The draft follows the brand rules."
                if not verdict.brand_rule_violations
                else f"Brand rule issues: {_summarize(list(verdict.brand_rule_violations))}.",
                blocking=True,
            )
        )
    return checks


def build_report(checks: list[ValidationCheck]) -> dict[str, Any]:
    return {
        "passed": all(check.passed for check in checks if check.blocking),
        "checks": [check.to_dict() for check in checks],
    }


def blocking_failures(checks: list[ValidationCheck]) -> list[ValidationCheck]:
    return [check for check in checks if check.blocking and not check.passed]
