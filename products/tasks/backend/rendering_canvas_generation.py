"""Generate React/TSX canvas source from a natural-language prompt."""

import re

from langchain_core.messages import HumanMessage, SystemMessage

from posthog.models import Team, User

from ee.hogai.llm import MaxChatAnthropic

GENERATION_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You generate a single self-contained React/TSX module that PostHog Code renders inside a
constrained sandbox. Your entire response must be valid TSX — no prose, no markdown fences,
no leading/trailing commentary. Output the module source and nothing else.

Hard constraints (any violation causes the result to be rejected):
- Define a single React component as a top-level `function App() { ... }` declaration.
  Do NOT use `export` or `export default` — the renderer evaluates the source as a
  script and `export` is a syntax error in that context. Just declare `function App`.
- Do not import from any package. Assume `React` is in scope.
- Do not use any of: fetch(), XMLHttpRequest, eval(), new Function(), dynamic import(),
  <script> tags, document.write, document.cookie, window.location, window.open.
- The only side-effect channel is the templating escape hatch `{{ @api.<dotted.path>(args) }}`.
  Use it to read PostHog data. Examples:
    {{ @api.projects.get(id) }}
    {{ @api.events.list(team_id, 10) }}
  Inside `{{ ... }}` you may not use further `{` or `}`. Anything other than
  `@api.<path>(...)` will be rejected.
- Keep the module under 256 KB.

Style:
- Tailwind utility classes are fine; assume Tailwind is loaded.
- Prefer small, readable components. Inline state with useState if needed.
- Do not invent props — the component is rendered with no props.
"""

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n(.*)\n```\s*$", re.DOTALL)
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _derive_name_from_prompt(prompt: str, max_words: int = 6, max_chars: int = 80) -> str:
    words = _WORD_RE.findall(prompt)[:max_words]
    if not words:
        return "Untitled canvas"
    name = " ".join(words)
    if len(name) > max_chars:
        name = name[:max_chars].rstrip()
    return name[:1].upper() + name[1:]


def generate_canvas_tsx(
    *,
    team: Team,
    user: User,
    prompt: str,
    name_hint: str | None = None,
) -> tuple[str, str]:
    """Generate a TSX module from a prompt. Returns (tsx, name).

    Raises whatever the underlying LangChain client raises on failure. The caller is
    responsible for running `validate_canvas_content` on the returned TSX before persisting.
    """
    llm = MaxChatAnthropic(
        model=GENERATION_MODEL,
        user=user,
        team=team,
        billable=True,
        streaming=False,
        disable_streaming=True,
        max_tokens=8192,
    )
    result = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])

    content = result.content
    if isinstance(content, list):
        # Anthropic sometimes returns a list of content blocks; concatenate text parts.
        text_parts = [
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "".join(text_parts)
    if not isinstance(content, str):
        content = str(content)

    tsx = _strip_code_fence(content)
    name = (name_hint or "").strip() or _derive_name_from_prompt(prompt)
    return tsx, name
