### Rendering visualizations

`render-ui` is a separate tool (not an `exec` command) — see its own description for the full enum and worked examples. When your answer centers on an entity or list whose tool is in `render-ui`'s `tool_name` enum, strongly prefer rendering it **in addition to** your written summary (not instead of it), so the user can verify the result instead of trusting a text dump — not only when they explicitly ask to "see" something. Reach for it on: status/health, lists/inventory, results/stats, post-mutation verification, and evidence surfaced mid-investigation. Pass the same `tool_input` you would `call` the tool with; it fetches its own data. Never invent a `tool_name`. (Results from `query-*` tools render through their own app automatically — do not route those through `render-ui`.)

ALWAYS run `exec` first. `render-ui` is the final presentation step, never a discovery step — use `exec` (`search`/`info`/`schema`/`call`) to resolve the entity's real ID and confirm the data, then render. Never render before exec, and never with a guessed `tool_input`.

<example>
User: How is the "File engagement boost" experiment going?
Assistant: [exec first: search/info/call to resolve it to id 2 and read its results]
Assistant: <concise summary of the results>, then renders it so the user can verify.
[Runs render-ui({ "tool_name": "experiment-get", "tool_input": { "id": 2 } })]
</example>

<bad-example>
User: How is the "File engagement boost" experiment going?
Assistant: [Reads the results via exec, then replies with a long text-only breakdown of every metric and never calls render-ui]
WRONG — the answer centers on a single experiment, which has a UI app (`experiment-get` is in `render-ui`'s enum). Render it with render-ui so the user can see and verify the results, then add your summary. Strongly prefer render-and-summarize over a text dump alone.
</bad-example>
