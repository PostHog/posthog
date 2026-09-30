import json
import dataclasses
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from anthropic import Anthropic

from posthog.dataclasses import frozen
from posthog.security.llm_prompt_sanitization import sanitize_user_text, strip_llm_framing_markers

from products.web_analytics.backend.content_autopilot.edits import PageEdit, apply_edits, page_headings
from products.web_analytics.backend.content_autopilot.llm import ContentAutopilotLLMError, Effort, call_json
from products.web_analytics.backend.content_autopilot.opportunities import engine_label, site_page_urls, top_site_pages
from products.web_analytics.backend.content_autopilot.prompts import (
    BRIEF_SCHEMA,
    BRIEF_SYSTEM_PROMPT,
    DRAFT_SCHEMA,
    DRAFT_SYSTEM_PROMPT,
    EDIT_SCHEMA,
    JUDGE_SCHEMA,
    JUDGE_SYSTEM_PROMPT,
    SAFETY_SCHEMA,
    SAFETY_SYSTEM_PROMPT,
    bullet_list,
    tagged,
)
from products.web_analytics.backend.content_autopilot.research import MAX_DOCUMENT_CHARS, ResearchBundle, SourceDocument
from products.web_analytics.backend.content_autopilot.site_discovery import site_host
from products.web_analytics.backend.content_autopilot.validation import (
    LINK_RE,
    JudgeVerdict,
    ValidationCheck,
    check_competitor_overlap,
    check_edit_placement,
    check_internal_links,
    check_ledger_sources,
    check_length,
    check_structure,
    check_structured_data,
    check_url_available,
    judge_checks,
    word_count,
)
from products.web_analytics.backend.models import ContentAutopilotProposal, ContentAutopilotSiteProfile

SAFETY_INPUT_CHARS = MAX_DOCUMENT_CHARS
BRIEF_SITE_PAGE_CHARS = 8_000
BRIEF_COMPETITOR_PAGE_CHARS = 6_000
DRAFT_SITE_PAGE_CHARS = 12_000
DRAFT_COMPETITOR_PAGE_CHARS = 4_000
ANSWER_CHARS = 3_000
MAX_PROMPT_CHARS = 2_000
BRIEF_MAX_TOKENS = 4_000
DRAFT_MAX_TOKENS = 32_000
DRAFT_TIMEOUT_SECONDS = 600.0
JUDGE_MAX_TOKENS = 8_000
SAFETY_MAX_TOKENS = 400
WRITING_EFFORT: Effort = "medium"
NEW_PAGE_WORD_BUDGET = 1_400
EDIT_WORD_SHARE = 0.4
MIN_EDIT_WORDS = 300
MAX_EDIT_WORDS = 1_200
PAGE_OPENING_CHARS = 2_000
MAX_KEY_SITE_PAGES = 200


@frozen
class SiteContext:
    name: str
    origin: str
    brand_rules: tuple[str, ...]
    site_urls: tuple[str, ...]
    key_pages: tuple[str, ...]


@frozen
class Draft:
    title: str
    description: str
    url_path: str
    markdown: str
    new_markdown: str
    edits: tuple[PageEdit, ...]
    unplaced_edits: tuple[str, ...]
    json_ld: str
    llms_txt_line: str
    source_ledger: tuple[dict[str, str], ...]
    competitor_ledger: tuple[dict[str, str], ...]


def _is_improvement(proposal_type: str, original_markdown: str) -> bool:
    return proposal_type == ContentAutopilotProposal.ProposalType.PAGE_IMPROVEMENT and bool(original_markdown)


def _targets_existing_page(proposal_type: str, research: ResearchBundle) -> bool:
    return proposal_type == ContentAutopilotProposal.ProposalType.PAGE_IMPROVEMENT and bool(research.target_url)


def word_budget(proposal_type: str, original_markdown: str) -> int:
    if not _is_improvement(proposal_type, original_markdown):
        return NEW_PAGE_WORD_BUDGET
    return max(MIN_EDIT_WORDS, min(MAX_EDIT_WORDS, round(word_count(original_markdown) * EDIT_WORD_SHARE)))


def site_context(profile: ContentAutopilotSiteProfile, snapshot: object = None) -> SiteContext:
    saved = snapshot if isinstance(snapshot, dict) else {}
    if saved.get("domain", profile.domain) != profile.domain:
        raise ContentAutopilotLLMError("The site's domain changed after this run started. Draft it again.")
    rules = saved.get("brand_rules", profile.brand_rules)
    site_urls = site_page_urls(profile)
    return SiteContext(
        name=profile.name,
        origin=profile.domain,
        brand_rules=tuple(sanitize_user_text(str(rule), 500) for rule in rules),
        site_urls=tuple(site_urls),
        key_pages=tuple(
            top_site_pages(profile.team, origin=profile.domain, page_urls=site_urls, limit=MAX_KEY_SITE_PAGES)
        ),
    )


def _screen(client: Anthropic, *, team_id: int, label: str, text: str) -> tuple[bool, str]:
    verdict = call_json(
        client,
        system=SAFETY_SYSTEM_PROMPT,
        user=tagged("site_page", text[:SAFETY_INPUT_CHARS], source=label),
        schema=SAFETY_SCHEMA,
        max_tokens=SAFETY_MAX_TOKENS,
        team_id=team_id,
        model=settings.CONTENT_AUTOPILOT_SAFETY_MODEL,
    )
    return bool(verdict.get("safe")), sanitize_user_text(str(verdict.get("reason", "")), 300)


def _screen_documents(
    client: Anthropic, *, team_id: int, documents: tuple[SourceDocument, ...]
) -> tuple[list[SourceDocument], list[str]]:
    kept: list[SourceDocument] = []
    skipped: list[str] = []
    for document in documents:
        safe, reason = _screen(client, team_id=team_id, label=document.url, text=document.text)
        if safe:
            kept.append(document)
        else:
            skipped.append(f"Left out {document.url} because it looked like an attempt to steer the AI: {reason}")
    return kept, skipped


def screen_research(
    client: Anthropic, *, team_id: int, research: ResearchBundle, answers: list[dict[str, str]]
) -> tuple[ResearchBundle, list[dict[str, str]]]:
    kept, screened_out = _screen_documents(client, team_id=team_id, documents=research.documents)
    skipped = [*research.skipped, *screened_out]
    kept_answers: list[dict[str, str]] = []
    for answer in answers:
        safe, reason = _screen(client, team_id=team_id, label=answer["engine"], text=answer["answer_text"])
        if safe:
            kept_answers.append(answer)
        else:
            skipped.append(f"Left out the {engine_label(answer['engine'])} answer: {reason}")
    return (
        ResearchBundle(
            prompt=research.prompt,
            target_url=research.target_url,
            documents=tuple(kept),
            link_candidates=research.link_candidates,
            skipped=tuple(skipped),
        ),
        kept_answers,
    )


def _documents_block(documents: tuple[SourceDocument, ...], *, tag: str, limit: int, full_url: str = "") -> str:
    if not documents:
        return f"<{tag}_none />"
    return "\n\n".join(
        tagged(
            tag,
            document.text if full_url and document.url == full_url else document.text[:limit],
            url=document.url,
            title=document.title[:200],
        )
        for document in documents
    )


def _site_block(site: SiteContext) -> str:
    return (
        f"Today's date: {timezone.now():%B %d, %Y}\n"
        f"Site: {site.name} ({site.origin})\nBrand rules:\n{bullet_list(list(site.brand_rules))}"
    )


def _prompt_block(prompt: str) -> str:
    return tagged("prompt", sanitize_user_text(prompt, MAX_PROMPT_CHARS))


def generate_brief(
    client: Anthropic,
    *,
    team_id: int,
    site: SiteContext,
    research: ResearchBundle,
    gap: dict[str, Any],
    answers: list[dict[str, str]],
    proposal_type: str,
    budget: int,
    site_pages: list[str],
) -> dict[str, Any]:
    engines_missing = [engine_label(engine) for engine in gap.get("engines_not_citing", [])]
    queries = [sanitize_user_text(str(query), 200) for query in gap.get("engine_search_queries", [])]
    answer_block = "\n\n".join(
        tagged(
            "engine_answer",
            strip_llm_framing_markers(answer["answer_text"], ANSWER_CHARS),
            engine=engine_label(answer["engine"]),
        )
        for answer in answers
    )
    target_note = (
        f"The engines cite {research.target_url} in some answers to this question. Improve that page."
        if _targets_existing_page(proposal_type, research)
        else "No page on the site is known to target this question. Pick a listed page to improve, or plan a new page."
    )
    user = "\n\n".join(
        [
            _site_block(site),
            _prompt_block(research.prompt),
            f"Engines that didn't cite the site: {', '.join(engines_missing) or 'none'}",
            f"Searches the engines ran:\n{bullet_list(queries)}",
            target_note,
            f"Word budget: about {budget} words of new or rewritten content.",
            f"Site pages, search results for the question first, then the most visited:\n{bullet_list(site_pages)}",
            answer_block or "<engine_answer_none />",
            _documents_block(research.site_documents, tag="site_page", limit=BRIEF_SITE_PAGE_CHARS),
            _documents_block(research.competitor_documents, tag="competitor_page", limit=BRIEF_COMPETITOR_PAGE_CHARS),
        ]
    )
    return call_json(
        client,
        system=BRIEF_SYSTEM_PROMPT,
        user=user,
        schema=BRIEF_SCHEMA,
        max_tokens=BRIEF_MAX_TOKENS,
        team_id=team_id,
        effort=WRITING_EFFORT,
    )


def _ledger(payload: dict[str, Any], key: str) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "claim": sanitize_user_text(str(item.get("claim", "")), 500),
            "source_url": sanitize_user_text(str(item.get("source_url", "")), 2000),
            "quote": sanitize_user_text(str(item.get("quote", "")), 500),
        }
        for item in payload.get(key, [])
        if isinstance(item, dict)
    )


def _draft_from_payload(payload: dict[str, Any], *, original_markdown: str = "") -> Draft:
    edits = tuple(
        edit
        for item in payload.get("edits", [])
        if isinstance(item, dict)
        and (
            edit := PageEdit.from_dict(
                {**item, "markdown": strip_llm_framing_markers(str(item.get("markdown", "")), 100_000)}
            )
        )
    )
    if "edits" in payload:
        applied = apply_edits(original_markdown, list(edits))
        markdown = applied.markdown
        new_markdown = "\n\n".join(edit.markdown for edit in edits)
        unplaced = applied.unplaced
    else:
        markdown = strip_llm_framing_markers(str(payload.get("markdown", "")), 400_000)
        new_markdown = markdown
        unplaced = ()
    return Draft(
        title=sanitize_user_text(str(payload.get("title", "")), 300),
        description=sanitize_user_text(str(payload.get("description", "")), 300),
        url_path=sanitize_user_text(str(payload.get("url_path", "")), 500),
        markdown=markdown,
        new_markdown=new_markdown,
        edits=edits,
        unplaced_edits=unplaced,
        json_ld=str(payload.get("json_ld", "")),
        llms_txt_line=sanitize_user_text(str(payload.get("llms_txt_line", "")), 500),
        source_ledger=_ledger(payload, "source_ledger"),
        competitor_ledger=_ledger(payload, "competitor_ledger"),
    )


def _repair_instruction(check: ValidationCheck) -> str:
    if not check.details:
        return f"- {check.label}: {check.message}"
    return (
        f"- {check.label}: remove each of these claims, or rewrite it so a page you were given supports it. "
        f"If no page supports it, delete it.\n" + "\n".join(f"  - {detail}" for detail in check.details)
    )


def generate_draft(
    client: Anthropic,
    *,
    team_id: int,
    site: SiteContext,
    research: ResearchBundle,
    brief: dict[str, Any],
    proposal_type: str,
    original_markdown: str,
    previous: Draft | None = None,
    failures: list[ValidationCheck] | None = None,
) -> Draft:
    improving = _is_improvement(proposal_type, original_markdown)
    budget = word_budget(proposal_type, original_markdown)
    sections = [
        _site_block(site),
        _prompt_block(research.prompt),
        f"Content brief:\n{json.dumps(brief, indent=2)}",
        f"Site URLs you may link to:\n{bullet_list(list(research.link_candidates))}",
        _documents_block(research.site_documents, tag="site_page", limit=DRAFT_SITE_PAGE_CHARS),
        _documents_block(research.competitor_documents, tag="competitor_page", limit=DRAFT_COMPETITOR_PAGE_CHARS),
    ]
    if improving:
        sections.append(
            f"Improve this existing page at {urlparse(research.target_url).path}. Return edits, not the whole page. "
            f"Your edits together should add or rewrite at most about {budget} words.\n"
            f"Headings on the page:\n{bullet_list(page_headings(original_markdown))}\n"
            + tagged("site_page", original_markdown, url=research.target_url, title="Page to improve")
        )
    else:
        sections.append(f"Write the full page in about {budget} words, and no more than {round(budget * 1.3)}.")
    if previous is not None and failures:
        failed = "\n".join(_repair_instruction(check) for check in failures)
        noun, corrected, attempt = (
            ("edits", "list of edits", json.dumps([edit.to_dict() for edit in previous.edits], indent=2))
            if improving
            else ("draft", "draft", previous.markdown)
        )
        sections.append(
            f"Your previous {noun} failed these checks. Fix every one and return the full corrected {corrected}.\n"
            + failed
            + "\n"
            + tagged("draft", attempt)
        )
    payload = call_json(
        client,
        system=DRAFT_SYSTEM_PROMPT,
        user="\n\n".join(sections),
        schema=EDIT_SCHEMA if improving else DRAFT_SCHEMA,
        max_tokens=DRAFT_MAX_TOKENS,
        team_id=team_id,
        effort=WRITING_EFFORT,
        timeout_seconds=DRAFT_TIMEOUT_SECONDS,
    )
    draft = _draft_from_payload(payload, original_markdown=original_markdown if improving else "")
    if _targets_existing_page(proposal_type, research):
        draft = dataclasses.replace(draft, url_path=urlparse(research.target_url).path or "/")
    return draft


def judge_draft(
    client: Anthropic, *, team_id: int, site: SiteContext, research: ResearchBundle, draft: Draft, improving: bool
) -> JudgeVerdict:
    sections = [
        _site_block(site),
        _prompt_block(research.prompt),
        _documents_block(
            research.site_documents, tag="site_page", limit=DRAFT_SITE_PAGE_CHARS, full_url=research.target_url
        ),
        _documents_block(research.competitor_documents, tag="competitor_page", limit=DRAFT_COMPETITOR_PAGE_CHARS),
    ]
    if improving:
        sections.append(tagged("page_opening", draft.markdown[:PAGE_OPENING_CHARS]))
    sections.append(tagged("draft", draft.new_markdown))
    payload = call_json(
        client,
        system=JUDGE_SYSTEM_PROMPT,
        user="\n\n".join(sections),
        schema=JUDGE_SCHEMA,
        max_tokens=JUDGE_MAX_TOKENS,
        team_id=team_id,
        effort=WRITING_EFFORT,
    )
    return JudgeVerdict(
        unsupported_claims=tuple(
            sanitize_user_text(str(claim), 300) for claim in payload.get("unsupported_claims", [])
        ),
        answers_prompt=bool(payload.get("answers_prompt")),
        answers_prompt_reason=sanitize_user_text(str(payload.get("answers_prompt_reason", "")), 500),
        brand_rule_violations=tuple(
            sanitize_user_text(str(violation), 300) for violation in payload.get("brand_rule_violations", [])
        ),
    )


def _same_page(first: str, second: str) -> bool:
    return [line.rstrip() for line in first.strip().splitlines()] == [
        line.rstrip() for line in second.strip().splitlines()
    ]


def validate_draft(
    client: Anthropic,
    *,
    team_id: int,
    site: SiteContext,
    research: ResearchBundle,
    draft: Draft,
    proposal_type: str,
    original_markdown: str = "",
) -> list[ValidationCheck]:
    improving = _is_improvement(proposal_type, original_markdown)
    checks = [
        check_structure(draft.markdown, baseline=original_markdown if improving else None),
        check_internal_links(draft.new_markdown, site_origin=site.origin, site_urls=list(site.site_urls)),
        check_competitor_overlap(draft.new_markdown, research),
        check_structured_data(draft.json_ld),
        check_url_available(
            draft.url_path,
            is_new_page=proposal_type == ContentAutopilotProposal.ProposalType.NEW_CONTENT,
            site_urls=list(site.site_urls),
        ),
        check_ledger_sources(list(draft.source_ledger), research, competitor_ledger=draft.competitor_ledger),
    ]
    if improving and _same_page(draft.markdown, original_markdown):
        checks.append(
            ValidationCheck(
                check_key="changes",
                label="Changes",
                passed=False,
                message="The draft doesn't change the page. Regenerate to try again.",
                blocking=True,
            )
        )
    else:
        checks.append(check_length(draft.new_markdown, budget=word_budget(proposal_type, original_markdown)))
    if draft.unplaced_edits:
        checks.append(check_edit_placement(draft.unplaced_edits))
    verdict = judge_draft(client, team_id=team_id, site=site, research=research, draft=draft, improving=improving)
    return checks + judge_checks(verdict, has_brand_rules=bool(site.brand_rules))


def _internal_link_urls(markdown: str, origin: str) -> list[str]:
    host = site_host(origin)
    urls: dict[str, None] = {}
    for target in LINK_RE.findall(markdown):
        if target.startswith("/") and not target.startswith("//"):
            urls[f"{origin}{target}"] = None
        elif (target_host := site_host(target)) and target_host == host:
            urls[target] = None
    return list(urls)


def content_package(draft: Draft, *, origin: str, skipped: tuple[str, ...]) -> dict[str, Any]:
    path = "/".join(segment for segment in draft.url_path.split("/") if segment not in {"", ".", ".."}) or "index"
    return {
        "file_path": f"{path}.md",
        "title": draft.title,
        "description": draft.description,
        "slug": path.rsplit("/", 1)[-1],
        "frontmatter": [{"key": "title", "value": draft.title}, {"key": "description", "value": draft.description}],
        "internal_links": _internal_link_urls(draft.markdown, origin),
        "source_notes": list(skipped),
        "json_ld": draft.json_ld,
        "llms_txt_line": draft.llms_txt_line,
        "edits": [edit.to_dict() for edit in draft.edits],
    }


def _without_kind(entry: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in entry.items() if key != "kind"}


def _added_blocks(markdown: str, original: str) -> str:
    existing = {block.strip() for block in original.split("\n\n")}
    return "\n\n".join(block for block in markdown.split("\n\n") if block.strip() and block.strip() not in existing)


def _draft_from_proposal(proposal: ContentAutopilotProposal) -> Draft:
    package = proposal.content_package if isinstance(proposal.content_package, dict) else {}
    file_path = str(package.get("file_path", ""))
    ledger = [entry for entry in proposal.source_ledger if isinstance(entry, dict)]
    improving = _is_improvement(proposal.proposal_type, proposal.original_markdown)
    return Draft(
        title=str(package.get("title", proposal.title)),
        description=str(package.get("description", "")),
        url_path="/" + file_path.removesuffix(".md").removesuffix(".mdx"),
        markdown=proposal.proposed_markdown,
        new_markdown=_added_blocks(proposal.proposed_markdown, proposal.original_markdown)
        if improving
        else proposal.proposed_markdown,
        edits=(),
        unplaced_edits=(),
        json_ld=str(package.get("json_ld", "")),
        llms_txt_line=str(package.get("llms_txt_line", "")),
        source_ledger=tuple(_without_kind(entry) for entry in ledger if entry.get("kind") != "competitor"),
        competitor_ledger=tuple(_without_kind(entry) for entry in ledger if entry.get("kind") == "competitor"),
    )
