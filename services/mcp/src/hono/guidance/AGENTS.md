# MCP guidance

A guidance rule adds one short notice to a tool result when a call matches the rule.
The engine in `engine.ts` evaluates the rules in `rules/` after each tool call.

## Where a fact goes

A fact about a tool has one home.
Decide the home before you write a rule, a description, or a response field.

| Home             | Holds                                     | Test                                                                                                                                              |
| ---------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tool description | How to form the call                      | You can write it without the arguments, the result, or the project. Defaults and match rules go here.                                             |
| Tool response    | What this result covers, as data          | It is true on every call, empty or not, and it holds no advice and names no other tool. The date range that a call searched goes here.            |
| Guidance rule    | What to check next in one specific state | It needs something the tool handler does not have: the session's earlier calls, project state from another endpoint, or the caller's tool roster. |

- **A guidance rule must not restate a tool description.**
  When agents ignore a description, change the description or the tool.
- **A guidance rule must not carry result data.**
  Add the field to the response in the product's API, also when another team owns that API.
- **A tool response must not hold advice.**
  "0 of 140 flags matched" is data. "Try `search`" is advice.

## What a notice says

- A notice states facts that the engine observed: the arguments of the call, the result, and project state that a lookup returned.
- A notice must not tell the agent to retry, and it must not guess a cause.
- A notice names a tool or a skill only when `requiresTool` lists it, so it never points at something the caller lacks.

## How a rule runs

- Rules run in the order of `rules/index.ts`, and the first rule that matches takes the call.
- The feature flag in `flag` decides only whether the text is sent.
  A matching call is stamped either way, with `mcp_guidance_rule` and `mcp_guidance_outcome` (`shown`, `flag_off`, `suppressed`, or `no_consent`) on the `$mcp_tool_call` event.
  `flag_off` calls are the control group.
- `condition` runs for every outcome, so it must not depend on the flag.
- All lookups of one evaluation in `product-state.ts` share one time budget, because the tool result waits for them.
  A lookup returns `undefined` when the answer is unknown, and a rule must stay silent then.
- `emptyResultRule` in `empty-result-rule.ts` builds a rule for a successful call with no rows.
  It skips later pages and, by default, projects with no events.
  `lib/empty-tool-result.ts` decides what counts as no rows.

## Before you add a rule

- Measure the case from `$mcp_tool_call` events first: how often it happens, and what agents do next.
  When agents take the result as the answer and move on, the result is expected and needs no rule.
- Give the rule a test row in `tests/hono/guidance-<product>.test.ts` for each call shape, including the shapes that must get no notice.
- Judge a shipped rule by `shown` against `flag_off`, on an outcome the notice can change.
