"""Render a LandingPageBuildSpec into a polished single-page static SaaS landing site.

Output: 5 files GitHub Pages can serve verbatim (no build step):

    index.html   — fully-structured page with per-section purpose-built layouts
    styles.css   — brand vars, Inter font, gradient utility classes, accordion polish
    script.js    — PostHog init + tiny scroll/nav interactivity
    .nojekyll    — disable Jekyll
    README.md    — repo doc

Two-layer rendering:

1. `_parse_section_copy` turns each section's markdown into structured chunks (headings,
   list items, key/value bullets, Q&A pairs). The LLM emits a small subset of markdown
   patterns and the parser is opinionated about how to read each.

2. A renderer registry keyed on section name (case-insensitive) maps each section to a
   purpose-built HTML layout: hero → eyebrow + display headline + CTA cluster; features
   → 3-up icon-card grid; FAQ → `<details>` accordion; pricing → tier cards; etc. Anything
   we don't have a dedicated renderer for falls back to a clean prose render.

Visual direction: Inter type + brand color as the only accent, gradient hero, soft white
cards on a tinted background, rounded primitives, generous vertical rhythm. Avoids the
"generic AI markdown dump" look on the previous iteration.
"""

import re
import html
import json
from collections.abc import Callable
from typing import Any

# ---------- inline markdown → HTML --------------------------------------------

_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _inline(text: str, *, link_class: str = "text-brand-primary underline underline-offset-2 hover:opacity-80") -> str:
    text = html.escape(text)
    text = _RE_LINK.sub(lambda m: f'<a href="{m.group(2)}" class="{link_class}">{m.group(1)}</a>', text)
    text = _RE_BOLD.sub(r"<strong>\1</strong>", text)
    text = _RE_ITALIC.sub(r"<em>\1</em>", text)
    return text


# ---------- section parsing into structured chunks ----------------------------


def _parse_section_copy(copy: str) -> dict[str, Any]:
    """Tokenize a section's markdown into the structured chunks renderers need.

    Returns a dict with:
        - `headings`: list of {level, text} in order of appearance
        - `paragraphs`: list of raw paragraph strings (no bullet, no heading)
        - `bullets`: list of {bold, rest} where `bold` is a leading **bolded** label and
          `rest` is everything after the `—`/`-`/`:` separator (empty when none).
        - `qa_pairs`: list of {question, answer} pairs, detected from lines that are a
          single bolded statement followed by 1+ paragraph lines.
        - `links`: list of {label, url} from inline `[label](url)` anywhere.
    """
    headings: list[dict[str, Any]] = []
    paragraphs: list[str] = []
    bullets: list[dict[str, str]] = []
    qa_pairs: list[dict[str, str]] = []
    links: list[dict[str, str]] = []

    for m in _RE_LINK.finditer(copy):
        links.append({"label": m.group(1), "url": m.group(2)})

    lines = copy.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            headings.append({"level": len(m.group(1)), "text": m.group(2)})
            i += 1
            continue

        # Q&A pattern: a line that's just **Question?** with no other content, immediately
        # followed by 1+ paragraph lines that aren't headings/bullets/another bold-only.
        bold_only = re.fullmatch(r"\s*\*\*([^*]+?)\*\*\s*", line)
        if bold_only:
            question = bold_only.group(1).strip()
            answer_lines: list[str] = []
            j = i + 1
            while (
                j < len(lines)
                and lines[j].strip()
                and not re.match(r"^#{1,6}\s+", lines[j])
                and not lines[j].lstrip().startswith("- ")
                and not re.fullmatch(r"\s*\*\*([^*]+?)\*\*\s*", lines[j])
            ):
                answer_lines.append(lines[j].strip())
                j += 1
            if answer_lines:
                qa_pairs.append({"question": question, "answer": " ".join(answer_lines)})
                i = j
                continue
            # Bold-only line with no answer — fall through, treat as paragraph below.

        if line.lstrip().startswith("- "):
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                item = lines[i].lstrip()[2:].strip()
                # Extract leading **bold** if present, then strip the separator.
                m2 = re.match(r"^\*\*([^*]+?)\*\*(\s*[—–\-:]\s*(.*))?$", item)
                if m2:
                    bullets.append({"bold": m2.group(1).strip(), "rest": (m2.group(3) or "").strip()})
                else:
                    bullets.append({"bold": "", "rest": item})
                i += 1
            continue

        # Paragraph — gather consecutive non-empty, non-special lines.
        para: list[str] = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not re.match(r"^#{1,6}\s+", lines[i])
            and not lines[i].lstrip().startswith("- ")
        ):
            para.append(lines[i].strip())
            i += 1
        if para:
            paragraphs.append(" ".join(para))

    return {
        "headings": headings,
        "paragraphs": paragraphs,
        "bullets": bullets,
        "qa_pairs": qa_pairs,
        "links": links,
    }


# ---------- small helpers -----------------------------------------------------


def _kebab_case(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "section"


def _safe_palette_color(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    match = re.search(r"#[0-9a-fA-F]{3,8}", value)
    return match.group(0) if match else fallback


def _primary_cta(parsed: dict[str, Any]) -> dict[str, str] | None:
    return parsed["links"][0] if parsed["links"] else None


def _secondary_cta(parsed: dict[str, Any]) -> dict[str, str] | None:
    return parsed["links"][1] if len(parsed["links"]) > 1 else None


# ---------- per-section renderers ---------------------------------------------


def _render_nav(*, section: dict[str, Any], project_name: str, sections_all: list[dict[str, Any]]) -> str:
    """Sticky top nav. Brand on left, anchor links + primary CTA on right."""
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    cta = _primary_cta(parsed)
    # Pick a handful of upcoming section names for the nav — filter out Nav/Hero/Footer/CTA.
    skip_names = {"nav bar", "nav", "hero", "footer", "final cta"}
    nav_targets = [s.get("name") or "" for s in sections_all if (s.get("name") or "").lower() not in skip_names][:5]
    link_html = "\n".join(
        f'<a href="#{_kebab_case(n)}" class="text-sm text-slate-600 hover:text-slate-900 transition-colors">{html.escape(n)}</a>'
        for n in nav_targets
    )
    cta_html = (
        f'<a href="{cta["url"]}" class="ml-2 inline-flex items-center rounded-full bg-brand-primary px-4 py-2 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity">{html.escape(cta["label"])}</a>'
        if cta
        else ""
    )
    brand = html.escape(project_name)
    return f"""
<header class="sticky top-0 z-50 backdrop-blur bg-white/80 border-b border-slate-200">
    <nav class="mx-auto max-w-6xl px-6 h-16 flex items-center justify-between">
        <a href="#" class="flex items-center gap-2 font-semibold text-slate-900">
            <span class="inline-block h-7 w-7 rounded-lg bg-gradient-to-br from-brand-primary to-brand-accent"></span>
            {brand}
        </a>
        <div class="hidden md:flex items-center gap-6">
            {link_html}
            {cta_html}
        </div>
    </nav>
</header>
""".strip()


def _render_hero(*, section: dict[str, Any], project_name: str) -> str:
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = parsed["headings"][0]["text"] if parsed["headings"] else project_name
    subhead = parsed["paragraphs"][0] if parsed["paragraphs"] else ""
    primary = _primary_cta(parsed)
    secondary = _secondary_cta(parsed)

    primary_html = (
        f'<a href="{primary["url"]}" class="inline-flex items-center justify-center rounded-full bg-brand-primary px-7 py-3 text-base font-semibold text-white shadow-lg shadow-brand-primary/25 hover:opacity-90 transition-opacity">{html.escape(primary["label"])}</a>'
        if primary
        else ""
    )
    secondary_html = (
        f'<a href="{secondary["url"]}" class="inline-flex items-center justify-center rounded-full border border-slate-300 bg-white/70 px-7 py-3 text-base font-semibold text-slate-900 hover:bg-white transition-colors">{html.escape(secondary["label"])}</a>'
        if secondary
        else ""
    )
    return f"""
<section id="hero" class="relative overflow-hidden">
    <div class="absolute inset-0 -z-10 bg-gradient-to-b from-brand-neutral via-white to-white"></div>
    <div class="absolute -top-32 left-1/2 -z-10 -translate-x-1/2 h-[36rem] w-[72rem] rounded-full bg-brand-primary/10 blur-3xl"></div>
    <div class="mx-auto max-w-4xl px-6 pt-20 pb-16 md:pt-32 md:pb-24 text-center">
        <p class="text-sm uppercase tracking-widest text-brand-primary font-semibold">{html.escape(project_name)}</p>
        <h1 class="mt-4 text-4xl md:text-6xl font-bold tracking-tight text-slate-900 leading-[1.05]">{_inline(title, link_class="text-brand-primary")}</h1>
        <p class="mt-6 text-lg md:text-xl text-slate-600 max-w-2xl mx-auto leading-relaxed">{_inline(subhead, link_class="text-brand-primary underline")}</p>
        <div class="mt-10 flex flex-wrap gap-3 justify-center">
            {primary_html}
            {secondary_html}
        </div>
    </div>
</section>
""".strip()


def _render_social_proof(*, section: dict[str, Any]) -> str:
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = (
        parsed["headings"][0]["text"]
        if parsed["headings"]
        else (parsed["paragraphs"][0] if parsed["paragraphs"] else "Trusted by founders shipping today")
    )
    # Use the section's bullets as logo placeholders — render as text chips since we have no logos.
    items = [b["bold"] or b["rest"] for b in parsed["bullets"]] or [
        "YC",
        "Indie Hackers",
        "Product Hunt",
        "Hacker News",
    ]
    chips = "\n".join(
        f'<span class="text-slate-400 font-semibold tracking-wide text-sm md:text-base">{html.escape(item)}</span>'
        for item in items[:8]
    )
    return f"""
<section id="social-proof" class="border-y border-slate-100 bg-white py-10">
    <div class="mx-auto max-w-5xl px-6">
        <p class="text-center text-xs uppercase tracking-widest text-slate-500 mb-6">{html.escape(title)}</p>
        <div class="flex flex-wrap justify-center items-center gap-x-10 gap-y-4">
            {chips}
        </div>
    </div>
</section>
""".strip()


_FEATURE_ICONS = [
    # Hand-picked simple inline SVG glyphs — varied enough that 3-up grids don't look monotonous.
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-6 w-6"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-6 w-6"><path d="M13 2L3 14h7v8l10-12h-7V2z"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-6 w-6"><circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-6 w-6"><path d="M12 2v20M2 12h20"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-6 w-6"><path d="M3 12l3-9 6 18 3-9h6"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-6 w-6"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6v6H9z"/></svg>',
]


def _render_features(*, section: dict[str, Any]) -> str:
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = parsed["headings"][0]["text"] if parsed["headings"] else (section.get("name") or "Features")
    intro = parsed["paragraphs"][0] if parsed["paragraphs"] else ""
    bullets = parsed["bullets"] or [{"bold": "", "rest": p} for p in parsed["paragraphs"][1:]]
    cards = []
    for idx, b in enumerate(bullets[:6]):
        icon = _FEATURE_ICONS[idx % len(_FEATURE_ICONS)]
        label = b.get("bold") or b.get("rest") or ""
        body = b.get("rest") if b.get("bold") else ""
        cards.append(
            f'<div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all">\n'
            f'    <div class="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-brand-primary/10 text-brand-primary">{icon}</div>\n'
            f'    <h3 class="mt-5 text-lg font-semibold text-slate-900">{_inline(label)}</h3>\n'
            f'    <p class="mt-2 text-slate-600 leading-relaxed">{_inline(body)}</p>\n'
            f"</div>"
        )
    cards_html = "\n".join(cards)
    return f"""
<section id="{_kebab_case(section.get("name") or "features")}" class="bg-brand-neutral py-20 md:py-28">
    <div class="mx-auto max-w-6xl px-6">
        <div class="max-w-2xl">
            <h2 class="text-3xl md:text-4xl font-bold tracking-tight text-slate-900">{_inline(title)}</h2>
            {f'<p class="mt-4 text-lg text-slate-600">{_inline(intro)}</p>' if intro else ""}
        </div>
        <div class="mt-12 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {cards_html}
        </div>
    </div>
</section>
""".strip()


def _render_how_it_works(*, section: dict[str, Any]) -> str:
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = parsed["headings"][0]["text"] if parsed["headings"] else (section.get("name") or "How it works")
    intro = parsed["paragraphs"][0] if parsed["paragraphs"] else ""
    steps = parsed["bullets"]
    step_html = []
    for idx, b in enumerate(steps[:6]):
        label = b.get("bold") or b.get("rest") or ""
        body = b.get("rest") if b.get("bold") else ""
        step_html.append(
            f'<div class="relative pl-14">\n'
            f'    <div class="absolute left-0 top-0 inline-flex h-10 w-10 items-center justify-center rounded-full bg-brand-primary text-white font-bold">{idx + 1}</div>\n'
            f'    <h3 class="text-lg font-semibold text-slate-900">{_inline(label)}</h3>\n'
            f'    <p class="mt-1 text-slate-600 leading-relaxed">{_inline(body)}</p>\n'
            f"</div>"
        )
    return f"""
<section id="{_kebab_case(section.get("name") or "how-it-works")}" class="bg-white py-20 md:py-28">
    <div class="mx-auto max-w-5xl px-6">
        <div class="max-w-2xl">
            <h2 class="text-3xl md:text-4xl font-bold tracking-tight text-slate-900">{_inline(title)}</h2>
            {f'<p class="mt-4 text-lg text-slate-600">{_inline(intro)}</p>' if intro else ""}
        </div>
        <div class="mt-12 grid gap-10 md:grid-cols-2">
            {"".join(step_html)}
        </div>
    </div>
</section>
""".strip()


def _render_problem_statement(*, section: dict[str, Any]) -> str:
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = parsed["headings"][0]["text"] if parsed["headings"] else (section.get("name") or "The problem")
    body_paragraphs = parsed["paragraphs"]
    body_html = "".join(
        f'<p class="text-lg text-slate-600 mt-4 leading-relaxed">{_inline(p)}</p>' for p in body_paragraphs
    )
    # Optional bullets become pain-point callouts.
    pains_html = ""
    if parsed["bullets"]:
        items = "\n".join(
            f'<li class="flex gap-3 items-start"><span class="mt-1.5 inline-block h-1.5 w-1.5 rounded-full bg-brand-accent flex-none"></span><span class="text-slate-700">{_inline((b.get("bold") + " — " if b.get("bold") else "") + (b.get("rest") or ""))}</span></li>'
            for b in parsed["bullets"][:6]
        )
        pains_html = f'<ul class="mt-8 space-y-3">{items}</ul>'
    return f"""
<section id="{_kebab_case(section.get("name") or "problem")}" class="bg-white py-20 md:py-28">
    <div class="mx-auto max-w-4xl px-6">
        <h2 class="text-3xl md:text-4xl font-bold tracking-tight text-slate-900">{_inline(title)}</h2>
        {body_html}
        {pains_html}
    </div>
</section>
""".strip()


def _render_pricing(*, section: dict[str, Any]) -> str:
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = parsed["headings"][0]["text"] if parsed["headings"] else "Pricing"
    intro = parsed["paragraphs"][0] if parsed["paragraphs"] else ""
    # Pricing tiers — look for H3 headings; each H3 starts a tier and its bullets/paragraphs
    # belong to it. Fall back to the bullet list if no H3s found.
    h3s = [h for h in parsed["headings"] if h["level"] == 3]
    tier_cards = []
    if h3s:
        # Re-walk the raw copy splitting on H3 markers.
        copy = section.get("copy_hooks") or ""
        chunks = re.split(r"^###\s+", copy, flags=re.MULTILINE)
        for chunk in chunks[1:]:
            tier_lines = chunk.splitlines()
            tier_name = tier_lines[0].strip() if tier_lines else ""
            tier_body = _parse_section_copy("\n".join(tier_lines[1:]))
            price = tier_body["paragraphs"][0] if tier_body["paragraphs"] else ""
            items = "".join(
                f'<li class="flex gap-2 items-start"><svg viewBox="0 0 20 20" class="h-5 w-5 text-brand-primary flex-none mt-0.5" fill="currentColor"><path fill-rule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-8 8a1 1 0 01-1.4 0l-4-4a1 1 0 011.4-1.4L8 12.6l7.3-7.3a1 1 0 011.4 0z" clip-rule="evenodd"/></svg><span class="text-slate-700">{_inline((b.get("bold") + " — " if b.get("bold") else "") + (b.get("rest") or ""))}</span></li>'
                for b in tier_body["bullets"][:8]
            )
            tier_cards.append(
                f'<div class="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm flex flex-col">\n'
                f'    <h3 class="text-xl font-semibold text-slate-900">{html.escape(tier_name)}</h3>\n'
                f'    <p class="mt-3 text-3xl font-bold text-slate-900">{_inline(price)}</p>\n'
                f'    <ul class="mt-6 space-y-3 flex-1">{items}</ul>\n'
                f"</div>"
            )
    else:
        for b in parsed["bullets"][:3]:
            label = b.get("bold") or b.get("rest")
            body = b.get("rest") if b.get("bold") else ""
            tier_cards.append(
                f'<div class="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">\n'
                f'    <h3 class="text-xl font-semibold text-slate-900">{_inline(label)}</h3>\n'
                f'    <p class="mt-3 text-slate-600 leading-relaxed">{_inline(body)}</p>\n'
                f"</div>"
            )
    return f"""
<section id="pricing" class="bg-brand-neutral py-20 md:py-28">
    <div class="mx-auto max-w-6xl px-6">
        <div class="text-center max-w-2xl mx-auto">
            <h2 class="text-3xl md:text-4xl font-bold tracking-tight text-slate-900">{_inline(title)}</h2>
            {f'<p class="mt-4 text-lg text-slate-600">{_inline(intro)}</p>' if intro else ""}
        </div>
        <div class="mt-12 grid gap-6 md:grid-cols-{min(max(len(tier_cards), 1), 3)}">
            {"".join(tier_cards)}
        </div>
    </div>
</section>
""".strip()


def _render_faq(*, section: dict[str, Any]) -> str:
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = parsed["headings"][0]["text"] if parsed["headings"] else "Frequently asked questions"
    pairs = parsed["qa_pairs"]
    items = []
    for idx, pair in enumerate(pairs):
        # Open the first one by default — gives the page some visible content on land.
        is_open = " open" if idx == 0 else ""
        items.append(
            f'<details class="group rounded-xl border border-slate-200 bg-white"{is_open}>\n'
            f'    <summary class="flex items-center justify-between cursor-pointer list-none p-5 text-left">\n'
            f'        <span class="text-base md:text-lg font-semibold text-slate-900">{_inline(pair["question"])}</span>\n'
            f'        <svg viewBox="0 0 24 24" class="h-5 w-5 text-slate-400 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>\n'
            f"    </summary>\n"
            f'    <div class="px-5 pb-5 text-slate-600 leading-relaxed">{_inline(pair["answer"])}</div>\n'
            f"</details>"
        )
    items_html = "\n".join(items)
    return f"""
<section id="faq" class="bg-white py-20 md:py-28">
    <div class="mx-auto max-w-3xl px-6">
        <h2 class="text-3xl md:text-4xl font-bold tracking-tight text-slate-900 text-center">{_inline(title)}</h2>
        <div class="mt-12 space-y-3">
            {items_html}
        </div>
    </div>
</section>
""".strip()


def _render_final_cta(*, section: dict[str, Any], project_name: str) -> str:
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = parsed["headings"][0]["text"] if parsed["headings"] else f"Ready to try {project_name}?"
    body = parsed["paragraphs"][0] if parsed["paragraphs"] else ""
    primary = _primary_cta(parsed)
    primary_html = (
        f'<a href="{primary["url"]}" class="inline-flex items-center justify-center rounded-full bg-white px-7 py-3 text-base font-semibold text-brand-primary shadow-lg hover:bg-white/90 transition-colors">{html.escape(primary["label"])}</a>'
        if primary
        else ""
    )
    return f"""
<section id="final-cta" class="relative overflow-hidden">
    <div class="absolute inset-0 -z-10 bg-gradient-to-br from-brand-primary via-brand-primary to-brand-accent"></div>
    <div class="mx-auto max-w-4xl px-6 py-20 md:py-28 text-center">
        <h2 class="text-3xl md:text-5xl font-bold tracking-tight text-white">{_inline(title, link_class="text-white underline")}</h2>
        {f'<p class="mt-4 text-lg md:text-xl text-white/85 max-w-2xl mx-auto leading-relaxed">{_inline(body, link_class="text-white underline")}</p>' if body else ""}
        <div class="mt-8 flex justify-center">{primary_html}</div>
    </div>
</section>
""".strip()


def _render_footer(*, section: dict[str, Any] | None, project_name: str) -> str:
    body_html = ""
    if section is not None:
        parsed = _parse_section_copy(section.get("copy_hooks") or "")
        if parsed["paragraphs"]:
            body_html = f'<p class="mt-2 text-sm text-slate-500 max-w-md">{_inline(parsed["paragraphs"][0])}</p>'
    return f"""
<footer class="border-t border-slate-200 bg-white">
    <div class="mx-auto max-w-6xl px-6 py-12 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
            <div class="flex items-center gap-2 font-semibold text-slate-900">
                <span class="inline-block h-6 w-6 rounded-lg bg-gradient-to-br from-brand-primary to-brand-accent"></span>
                {html.escape(project_name)}
            </div>
            {body_html}
        </div>
        <p class="text-sm text-slate-500">© <span id="year"></span> {html.escape(project_name)}. Built with PostHog founder mode.</p>
    </div>
</footer>
""".strip()


def _render_generic(*, section: dict[str, Any]) -> str:
    """Fallback for unrecognized sections — clean prose render, never the ugly Markdown dump."""
    parsed = _parse_section_copy(section.get("copy_hooks") or "")
    title = parsed["headings"][0]["text"] if parsed["headings"] else (section.get("name") or "Section")
    body_html_parts = []
    for p in parsed["paragraphs"]:
        body_html_parts.append(f'<p class="text-slate-600 leading-relaxed mt-4">{_inline(p)}</p>')
    if parsed["bullets"]:
        items = "".join(
            f'<li class="text-slate-700">{_inline((b.get("bold") + " — " if b.get("bold") else "") + (b.get("rest") or ""))}</li>'
            for b in parsed["bullets"]
        )
        body_html_parts.append(f'<ul class="list-disc pl-6 space-y-2 mt-6 marker:text-brand-accent">{items}</ul>')
    return f"""
<section id="{_kebab_case(section.get("name") or "section")}" class="bg-white py-20 md:py-24">
    <div class="mx-auto max-w-3xl px-6">
        <h2 class="text-3xl md:text-4xl font-bold tracking-tight text-slate-900">{_inline(title)}</h2>
        {"".join(body_html_parts)}
    </div>
</section>
""".strip()


# ---------- registry + page assembly ------------------------------------------


def _section_renderer(name: str) -> Callable[..., str] | None:
    """Match a section's name (case-insensitive) to a purpose-built renderer.

    Returns None if no specific renderer exists — caller should use `_render_generic`.
    Nav and Footer are handled separately at page-assembly time so the registry skips them.
    """
    n = (name or "").lower().strip()
    if n in ("hero",):
        return lambda section, project_name, **_: _render_hero(section=section, project_name=project_name)
    if n in ("social proof", "logos", "logo bar"):
        return lambda section, **_: _render_social_proof(section=section)
    if n in ("features",):
        return lambda section, **_: _render_features(section=section)
    if n in ("how it works", "how-it-works"):
        return lambda section, **_: _render_how_it_works(section=section)
    if n in ("problem statement", "problem", "the problem"):
        return lambda section, **_: _render_problem_statement(section=section)
    if n in ("pricing", "plans"):
        return lambda section, **_: _render_pricing(section=section)
    if n in ("faq", "frequently asked questions", "faqs"):
        return lambda section, **_: _render_faq(section=section)
    if n in ("final cta", "cta", "call to action"):
        return lambda section, project_name, **_: _render_final_cta(section=section, project_name=project_name)
    return None


def _index_html(*, spec: dict[str, Any], project_name: str) -> str:
    seo = spec.get("seo_front_matter") if isinstance(spec.get("seo_front_matter"), dict) else {}
    title = (seo or {}).get("title") or project_name
    description = (seo or {}).get("meta_description") or ""
    sections = spec.get("page_sections") or []

    # Pull out Nav / Footer to render in fixed positions; everything else stays in order.
    nav_section = next(
        (s for s in sections if (s.get("name") or "").lower() in ("nav bar", "nav", "navbar", "navigation")), None
    )
    footer_section = next((s for s in sections if (s.get("name") or "").lower() in ("footer",)), None)
    body_sections = [
        s for s in sections if (s.get("name") or "").lower() not in ("nav bar", "nav", "navbar", "navigation", "footer")
    ]

    nav_html = _render_nav(section=nav_section or {}, project_name=project_name, sections_all=body_sections)
    section_html_parts: list[str] = []
    for s in body_sections:
        renderer = _section_renderer(s.get("name") or "")
        if renderer is not None:
            section_html_parts.append(renderer(section=s, project_name=project_name))
        else:
            section_html_parts.append(_render_generic(section=s))
    footer_html = _render_footer(section=footer_section, project_name=project_name)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <meta name="description" content="{html.escape(description)}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="styles.css">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    fontFamily: {{ sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'] }},
                    colors: {{
                        brand: {{
                            primary: 'var(--brand-primary)',
                            accent: 'var(--brand-accent)',
                            neutral: 'var(--brand-neutral)',
                        }},
                    }},
                }},
            }},
        }}
    </script>
</head>
<body class="bg-white text-slate-900 font-sans antialiased">
{nav_html}
<main>
{chr(10).join(section_html_parts)}
</main>
{footer_html}
<script src="script.js"></script>
</body>
</html>
"""


def _styles_css(brand: dict[str, Any]) -> str:
    palette = brand.get("palette") if isinstance(brand, dict) else {}
    palette_text = palette.get("text") if isinstance(palette, dict) else None
    primary = _safe_palette_color(palette_text, "#2563EB")
    accent = _safe_palette_color(palette_text, "#F59E0B") if palette_text else "#F59E0B"
    return f""":root {{
    --brand-primary: {primary};
    --brand-accent: {accent};
    --brand-neutral: #F8FAFC;
}}

html {{ scroll-behavior: smooth; }}

/* Hide the default `<details>` marker so our custom chevron is the only affordance. */
summary::-webkit-details-marker {{ display: none; }}
summary::marker {{ content: ''; }}

/* Subtle entrance animation for sections as they scroll in. */
@media (prefers-reduced-motion: no-preference) {{
    section {{ animation: founder-fade-in .6s ease-out both; }}
    @keyframes founder-fade-in {{
        from {{ opacity: 0; transform: translateY(8px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}
}}
"""


def _script_js(project_name: str) -> str:
    # Lightweight runtime: PostHog init (gated on a meta tag) + auto-fill the footer year.
    return f"""// Generated by PostHog founder mode for {json.dumps(project_name)}.
(function () {{
    const yearEl = document.getElementById('year');
    if (yearEl) yearEl.textContent = new Date().getFullYear();

    const meta = document.querySelector('meta[name="posthog-key"]');
    const key = meta ? meta.content : null;
    if (!key) return;
    const host = (document.querySelector('meta[name="posthog-host"]') || {{}}).content || 'https://us.i.posthog.com';
    !function(t,e){{var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){{function g(t,e){{var o=e.split('.');2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){{t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}}}(p=t.createElement('script')).type='text/javascript',p.crossOrigin='anonymous',p.async=!0,p.src=s.api_host.replace('.i.posthog.com','-assets.i.posthog.com')+'/static/array.js',(r=t.getElementsByTagName('script')[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a='posthog',u.people=u.people||[],u.toString=function(t){{var e='posthog';return'posthog'!==a&&(e+='.'+a),t||(e+=' (stub)'),e}},u.people.toString=function(){{return u.toString(1)+'.people (stub)'}},o='init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug getPageViewId captureTraceFeedback captureTraceMetric'.split(' '),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])}},e.__SV=1)}}(document,window.posthog||[]);
    posthog.init(key, {{api_host: host, person_profiles: 'identified_only'}});
}})();
"""


def _readme(project_name: str) -> str:
    return (
        f"# {project_name}\n\n"
        "Static SaaS landing page generated by **PostHog founder mode**.\n\n"
        "## Stack\n\n"
        "- Plain `index.html` + `styles.css` + `script.js` — no build step.\n"
        "- Tailwind CSS via CDN, so any utility class works.\n"
        "- Inter via Google Fonts.\n"
        "- Brand palette wired into `--brand-primary` / `--brand-accent` CSS variables.\n\n"
        "## Sections\n\n"
        "Per-section purpose-built layouts: Hero, Social proof, Features (3-up icon cards), "
        "How it works (numbered steps), Problem statement, Pricing tiers, FAQ accordion, "
        "Final CTA gradient band, Footer. Markdown in the spec's `copy_hooks` is parsed "
        "into structured chunks before rendering — bullets become cards, **bold** lines "
        "followed by paragraphs become FAQ Q&A pairs, etc.\n\n"
        "## Enabling analytics\n\n"
        "Add to `<head>`:\n\n"
        "```html\n"
        '<meta name="posthog-key" content="phc_xxxxxxxxxxxxxxxxxxx">\n'
        "```\n\n"
        "## Iterating\n\n"
        "Edit `index.html` and `styles.css` directly. Commit + push — GitHub Pages auto-deploys.\n"
    )


# ---------- orchestrator -----------------------------------------------------


def render_spec_to_files(*, spec: dict[str, Any], project_name: str) -> dict[str, str]:
    if not isinstance(spec, dict):
        raise ValueError("spec must be a dict (the `marketing_page.page` payload)")
    brand_raw = spec.get("brand")
    brand: dict[str, Any] = brand_raw if isinstance(brand_raw, dict) else {}
    return {
        "index.html": _index_html(spec=spec, project_name=project_name),
        "styles.css": _styles_css(brand),
        "script.js": _script_js(project_name),
        ".nojekyll": "",
        "README.md": _readme(project_name),
    }
