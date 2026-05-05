SYSTEM_PROMPT = """You are generating realistic synthetic feedback signals for testing a customer-feedback grouping pipeline at PostHog.

PostHog is a product analytics platform. Surface areas include: Product analytics (insights, dashboards, funnels, retention, paths, lifecycle, stickiness), Session replay, Surveys, Feature flags, Experiments, Web analytics, Data warehouse, Workflows / hog flows, LLM analytics, Error tracking, SQL editor, Notebooks, Cohorts, Toolbar / autocapture.

Your job: produce a JSON object matching this schema:
{
  "signals": [
    {"title": "short headline", "body": "longer description"},
    ...
  ]
}

Each signal must read like a realistic GitHub issue / Linear ticket / support request from a PostHog user — feature requests, bug reports, usability complaints, or questions. Use natural varied user voices (frustrated, polite, technical, vague non-technical). Bodies should typically be 50-400 words and may include reproduction steps, code snippets, expected vs actual behavior, browser / OS context.

Constraints:
- Do NOT mention "synthetic", "test", "fixture", "AI-generated", or similar — content should be indistinguishable from real user feedback.
- Do NOT include URLs to real PostHog Slack threads, Notion docs, or internal links — keep it user-facing.
- Each title MUST be at least 10 characters and at most 300; each body MUST be at least 20 characters and at most 4000.
- Output a SINGLE JSON object only. No prose, no markdown fences, no surrounding text."""


VARIATION_GUIDANCE = {
    "dup": (
        "Each signal should describe THE SAME problem in nearly identical words. "
        "Vary only minor phrasing, casing, or punctuation. The grouping system "
        "should treat them as exact duplicates."
    ),
    "paraphrase": (
        "Each signal should describe the SAME underlying problem but phrased differently — "
        "different vocabulary, sentence structure, level of detail, persona. They are "
        "unmistakably the same root issue and should merge into one report."
    ),
    "variant": (
        "Each signal should target the SAME feature area but a slightly different "
        "user-facing aspect, edge case, or sub-problem. They share the topic but "
        "are individually distinct enough that a human PM might consider them separate "
        "tickets that all roll up to the same epic."
    ),
    "tangent": (
        "Each signal should be vaguely topic-adjacent (same product surface, similar "
        "vocabulary) but address fundamentally different concerns. The grouping system "
        "should NOT merge them — they share words but not root cause."
    ),
}

VARIATION_CHOICES = tuple(VARIATION_GUIDANCE.keys())


def build_user_prompt(*, theme: str, count: int, variation: str, extra_steering: str | None = None) -> str:
    if variation not in VARIATION_GUIDANCE:
        raise ValueError(f"Unknown variation {variation!r}; must be one of {VARIATION_CHOICES}")
    guidance = VARIATION_GUIDANCE[variation]
    extra = f"\n\nAdditional steering:\n{extra_steering.strip()}\n" if extra_steering else ""
    return (
        f"Theme: {theme}\n\n"
        f"Count: {count}\n\n"
        f"Variation: {variation}\n{guidance}\n"
        f"{extra}"
        f"Produce exactly {count} signals. Output the JSON object now."
    )
