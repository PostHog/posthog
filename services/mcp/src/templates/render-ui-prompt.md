Render an interactive, explorable PostHog visualization for the user. Strongly prefer rendering whenever your answer centers on an analytics query, specific entity, or list that has a UI app — a trends or funnel result, experiment (or its results), survey (or its stats), cohort, action, error-tracking issue, session recording, trace, or workflow, plus the list view for most — so the user can see and verify it, not just read a text summary. Render in addition to your written summary, not instead of it, and not only when the user explicitly asks to "see" something.

ALWAYS run `exec` first — `render-ui` is the final presentation step, never a discovery step. Use `exec` (`search` → `info` → `schema` → `call`) to resolve the entity (look up its real ID), confirm the data exists, and gather what you need for your written summary; only then render. Never render with a guessed `tool_input`.

`tool_name` must be a tool from the enum; `tool_input` is the same input you would `call` it with — which you already know from your exec work. The widget fetches its own data, so you may skip a *redundant* `call` of that same UI-app tool purely to populate the widget — but that is the only `call` you may skip, never the discovery/verification workflow. Never invent a `tool_name`.

When to render (always after exec, alongside your written answer):

- Show me / pull up X → its detail tool, e.g. `render-ui({ "tool_name": "survey-get", "tool_input": { "id": "abc123" } })`
- Status, "how is X going" → `render-ui({ "tool_name": "experiment-get", "tool_input": { "id": 2 } })`
- Lists / inventory, "what do we have" → the `*-list` tool, e.g. `render-ui({ "tool_name": "experiment-list", "tool_input": {} })`
- Results / stats, "is it significant", "response rate" → the results tool, e.g. `render-ui({ "tool_name": "survey-stats", "tool_input": { "survey_id": "abc123" } })`
- Analytics queries → run the query with `exec` for your analysis, then render the same tool with the same input, e.g. `render-ui({ "tool_name": "query-trends", "tool_input": { ... } })`
- After a mutation (create/launch/pause/end/resolve) → the entity's detail tool, to confirm the change landed
- Evidence mid-investigation (a recording, error issue, trace) → render it inline, e.g. `render-ui({ "tool_name": "query-error-tracking-issue", "tool_input": { "issueId": "0190-..." } })`

<example>
User: How is the "File engagement boost" experiment going?
Assistant: [exec first: search experiment → info experiment-get → call to resolve it to id 2 and read its results]
Assistant: <concise summary — front-runner, significance, caveats>, then renders it so the user can verify.
[Calls render-ui({ "tool_name": "experiment-get", "tool_input": { "id": 2 } })]
<reasoning>exec first to resolve the id and gather the numbers; render last, alongside the summary.</reasoning>
</example>

<example>
User: What experiments are we running right now?
Assistant: [exec first: call experiment-list to read what's running for the summary]
Assistant: Four are running, then renders the interactive list rather than a markdown table.
[Calls render-ui({ "tool_name": "experiment-list", "tool_input": {} })]
</example>

<bad-example>
User: How is the "File engagement boost" experiment going?
Assistant: [Immediately calls render-ui with a guessed id, without any exec search/info/call first]
WRONG — render-ui is not a discovery tool. Run exec first to resolve the experiment's real id and read its results, then render — never render before exec or with a guessed input.
</bad-example>

<bad-example>
User: How is the "File engagement boost" experiment going?
Assistant: [Reads the results via exec, then replies with a long text-only breakdown of every metric and never calls render-ui]
WRONG — the answer centers on a single experiment that has a UI app (`experiment-get` is in the enum). Render it so the user can see and verify the results, then add your summary.
</bad-example>

<bad-example>
User: Show me a trends chart of weekly signups
Assistant: [Runs query-trends through exec, then replies with a text-only summary]
WRONG — after running the query for analysis, render `query-trends` with the same validated input so the user can explore the chart.
</bad-example>
