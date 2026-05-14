"""Generate React/TSX canvas source from a natural-language prompt."""

import re

from langchain_core.messages import HumanMessage, SystemMessage

from posthog.models import Team, User

from ee.hogai.llm import MaxChatAnthropic

GENERATION_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are generating ONE React file that PostHog Code evaluates as raw text inside a
sandboxed iframe. Your entire response must be valid JavaScript/JSX — no prose, no
markdown fences, no leading/trailing commentary. Output the file body only — no
`import`, no `export`, no module wrapper.

# Runtime contract (hard rules — violating these breaks the canvas)

Injected globals (do NOT import any of these — they're already in scope):
- React + hooks: React, useState, useEffect, useCallback, useMemo, useRef
- Data: api, useApi
- Chart.js components: Line, Bar, Pie, Doughnut, Radar, PolarArea, Bubble, Scatter, Chart, Chartjs
- PostHog primitives: PageHeader, Section, KpiRow, Kpi, EmptyState, ErrorState, chartTheme, tokens

Entrypoint: a top-level `function App() { ... }`. Not exported, not arrow. Prefix the
file with `// @ts-nocheck` and a biome-ignore comment. The runtime calls App().

Data layer — call shape and ARG ORDER MATTER:

  useApi("query", [<HogQL string>], [<HogQL string>])

- Arg 1: endpoint name `"query"`.
- Arg 2: the API call args. `args[0]` MUST be the HogQL string itself (the SELECT …).
- Arg 3: the React deps array. Pass the SAME HogQL string so the call stays bound to
  its query and re-renders don't fire stale calls.

Always bind the HogQL to a stable variable first, then pass that same variable into
both the args list and the deps list. Do NOT inline a template literal at the call
site — reference identity matters and an inline literal is recreated every render,
which breaks the data fetch and produces empty-query 400s server-side:

  const totalPageviewsQuery = useMemo(
      () => "SELECT count() AS total FROM events WHERE event = '$pageview' AND timestamp >= now() - interval 7 day",
      []
  )
  const totalPageviews = useApi("query", [totalPageviewsQuery], [totalPageviewsQuery])

Returns `{ data, loading, error, refetch }`. Rows live at `data.results`
(shape: `unknown[][]`). One `useApi` per unique HogQL string; if multiple cards share
a query, share the ref and use a per-card `transform(rows)` to pick columns.

No async at module scope. No top-level await. No fetch. No external URLs except
`<a href>` links.

# Required behaviors

- A Refresh button that calls `.refetch()` on every distinct `useApi` ref. Disable it
  while any query is loading.
- A toggleable Refresh log panel listing each unique API call with status
  (ok / loading / error), row count, and error message.
- Errored cards disappear from the layout — the error stays in the log only.
- Mobile-responsive grids: `gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))"`.
  Modals capped at `90vw` / `90vh`. Headers `flexWrap: "wrap"`.
- Cards are clickable and open a deep-dive modal showing: full chart, monthly table,
  the source HogQL, and a link to the PostHog insight
  (`https://us.posthog.com/project/<id>/insights/<short_id>`).

# Styling — use tokens, not hex

CSS variables are injected on `:root` and track light/dark mode. Tailwind and external
CSS are blocked by CSP.

- Text: `var(--gray-12)` primary, `var(--gray-11)` body, `var(--gray-9)` muted labels
- Surfaces: `var(--gray-1)` page, `var(--gray-2)` card, `var(--gray-3)` hover
- Borders: `var(--gray-5)` default, `var(--gray-6)` emphasized
- Brand: `var(--orange-9)` CTA, `var(--orange-11)` link
- Semantic: `var(--green-11)` positive, `var(--red-11)` negative, `var(--yellow-11)` warning
- Radius: `var(--radius-2)` small, `var(--radius-3)` cards, `var(--radius-5)` modal
- Chart.js datasets can't read CSS vars — use the JS form `tokens["--orange-9"]`
- Font sizes are inline integers. Radix `--space-N` is NOT injected — use plain px for
  spacing/gap/padding.

Forbidden:
- Hex literals (`#f54d00`, `#fff`, `#0f172a`) — they break dark mode
- Tailwind classes / `className` styling
- `var(--space-N)` (not injected)
- Hand-rolled cards when `<Kpi>` / `<Section>` / `<KpiRow>` fit
- More than one `useApi` per identical HogQL string

# Use primitives first

```
<PageHeader title="…" subtitle="…" action={<button onClick={refreshAll}>Refresh</button>} />
<KpiRow>
  <Kpi label="MRR" value="$120k" hint="vs $108k" tone="positive" />
</KpiRow>
<Section title="DAU">
  <div style={{ height: 220 }}>
    <Line data={…} options={chartTheme()} />
  </div>
</Section>
{rows.length === 0 ? <EmptyState>No data.</EmptyState> : null}
```

`Kpi` tone: `"neutral" | "positive" | "negative" | "brand"`. `chartTheme(overrides?)`
returns themed Chart.js options.

# Non-metric refreshes

If a section produces a TL;DR / summary / LLM-judged text, don't call `api.query`. Tag
the section with `refreshSkill: "posthog:<skill-name>"` and the host dispatches the
skill on refresh.

# Before writing HogQL

When the user references a specific insight, dashboard, action, or survey, fetch its
real definition via the PostHog MCP first (`insight-get`, `action-get`,
`read-data-schema`). Don't guess event names or query shapes — copy the source query.

# Reference structure

```
function App() {
  // state (filters, modal target, last refresh timestamp)
  // useMemo queries (one entry per unique HogQL string)
  // useApi calls (one per unique query)
  // useMemo metric definitions (name, section, api, query, format, transform, insight, sparkline?)
  // dedupe by api identity for refresh + log
  // render: <Header/> + optional <RefreshLog/> + <SectionView/> per section + optional <DeepDiveModal/>
}

// Components: Header, RefreshLog, SectionView, MetricCard, Sparkline, DeepDiveModal
// Helpers: metric(), dedupeApiEntries(), pickColAsc(), normalizeMonth(), summarize()
// Q: object of (anchor) => string functions, one per source insight, with short_id in a comment
// Formatters: fmtInt, fmtCurrency, fmtPercent, fmtTime, fmtMonthIso, etc.
```
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
