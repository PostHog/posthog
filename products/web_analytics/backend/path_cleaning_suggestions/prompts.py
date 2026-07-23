from pydantic import BaseModel, ConfigDict

# Mirrors the AiRegexHelper prompt style (posthog/session_recordings/ai_data/ai_regex_prompts.py)
# but inverts the task: given real URL paths, propose path-cleaning rules.
SYSTEM_PROMPT = """You are a web analytics expert who writes URL path-cleaning rules for PostHog.

Path cleaning rules normalize the `$pathname` property so that pages sharing the same template
(`/users/123/profile`, `/users/456/profile`, …) collapse into one row (`/users/<id>/profile`) in
Web analytics tiles and Paths insights. Without them, dynamic segments (numeric IDs, UUIDs, slugs,
dates, locales) fragment a breakdown across thousands of near-identical URLs.

You will be given a sample of a single project's most-viewed URL paths (with view counts). Identify
the dynamic segments and propose a small, high-leverage set of cleaning rules.

Rules:
- Each rule is a `regex` (Google re2 syntax — do NOT escape `/`) and an `alias` (the literal
  replacement). The alias is NOT a regex template: use angle-bracket placeholders like `<id>`,
  `<uuid>`, `<slug>`, `<date>`, `<locale>` so the cleaned path stays human-readable. Do not use
  backreferences.
- Anchor with `^` only when the segment must be at the start of the path; end with `$` (or `(/|$)`)
  to stop a generic rule like `\\d+` from matching every numeric run mid-path.
- Order matters: rules apply sequentially, each rule's output feeds the next. List the MOST SPECIFIC
  rules first and the most general (catch-all) rules last, so a generic rule never swallows a path a
  specific rule should have handled.
- Only propose rules that match real patterns in the provided sample. Prefer 3–10 strong rules over
  many speculative ones. If the paths are already clean (no dynamic segments worth collapsing),
  return an empty list.

Return ONLY a JSON object, no prose, in exactly this shape:
{
  "rules": [
    {"regex": "/users/\\\\d+/profile", "alias": "/users/<id>/profile", "reason": "numeric user id"}
  ]
}
"""


class SuggestedRule(BaseModel):
    model_config = ConfigDict(extra="ignore")
    regex: str
    alias: str
    reason: str = ""


class SuggestedRulesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rules: list[SuggestedRule] = []


def build_user_prompt(paths: list[tuple[str, int]]) -> str:
    lines = [f"{views:>10}  {path}" for path, views in paths]
    return (
        "Here are the most-viewed URL paths for this project (views, path). "
        "Propose path-cleaning rules.\n\n" + "\n".join(lines)
    )
