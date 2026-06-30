# Skill — designing MCP tool surfaces

> **DESIGN-STAGE — NOT SHIPPED YET.** There is no `spec.mcp.tools[]`
> authoring field today. The `mcp` trigger config is just
> `{ allow_restart }`, and an MCP-enabled agent exposes exactly one
> tool — the default `ask` — over its `/mcp` endpoint. Everything
> below about curating `spec.mcp.tools[]` is forward-looking design
> guidance: use it to _reason about_ what a curated surface should
> look like, but **do not author a `spec.mcp.tools[]` block** — the
> spec parser doesn't accept one, and it would fail validation. The
> only field you set today is `triggers[].config.allow_restart` on
> the `mcp` trigger.

How to design the MCP surface an agent **exposes**. This is about
agents-as-MCP-servers, not about consuming MCPs at runtime (that's
`spec.mcps[]` — load `platform-mental-model` to keep the two
straight).

## When this skill applies

An agent has the `mcp` trigger (or is being designed to). The
user wants to make it callable from Claude Code / Cursor / the
MCP Inspector / another agent. The questions are: what tools to
expose, what to call them, how to describe them.

## The default — `ask`

Every MCP-trigger-enabled agent gets one free tool: `ask({
message, session_id? })`. The connecting client's LLM routes
based on the agent's top-level description. Continuation via
optional `session_id`.

This is enough for most agents. Don't over-engineer.

## When to add curated tools

> **NOT SHIPPED.** `spec.mcp.tools[]` is design-stage only (v1 work
> in `agent-as-mcp-server.md` §7) — currently the default `ask` is
> the only thing exposed and the spec parser rejects a `tools[]`
> block. Treat this section as a design rubric for when curated
> tools _would_ be worth it, not as something you can author today.

Once it ships, `spec.mcp.tools[]` will let the author declare typed
entry points beyond `ask`. It would be worth adding when:

- The agent has **distinct workflows**, each with a known input
  shape. A refund-processing agent has `request_refund({ order_id,
reason })` as a typed entry; the connecting LLM routes to it
  reliably from a user message like "refund order 1234".
- The agent has **structured inputs that don't fit a chat message**
  cleanly. E.g. a date range + filters + a specific question.
- The agent is going to be called **programmatically** by another
  system, not by a human conversational LLM.

If the exposed MCP/tools act on a third-party API as the user, wire an
identity provider — see the `authenticating-as-the-user` playbook.

Don't add curated tools when:

- The agent's job is genuinely conversational
- You can't write a one-line description that distinguishes the
  tool from `ask`
- You're tempted to add 5+ tools — usually a sign the agent should
  be split

## Naming

Verbs. Lowercase snake_case. Specific.

| Good                | Bad         | Why                                              |
| ------------------- | ----------- | ------------------------------------------------ |
| `request_refund`    | `refund`    | Verb makes the action clear to the routing LLM   |
| `inspect_agent`     | `agent`     | "agent" is a noun; the tool does something to it |
| `audit_team_agents` | `audit_all` | Specific scope — "audit all what?"               |
| `summarize_session` | `summarize` | Could be summarizing anything                    |
| `handle_ticket`     | `do_thing`  | "do_thing" is the perennial bad-tool-name        |

Stick to one word for the verb, one or two for the object. Names
over 4 words usually mean the tool does too much.

## Descriptions — the most important field

The connecting LLM's only signal about when to call this tool.
Treat it like ad copy — concrete, distinctive, action-oriented.

Bad: "This tool handles refund requests."
Better: "Submit a refund request for a customer order. Use when
the user mentions an order number and wants money back."

Bad: "Inspect agents."
Better: "Summarize an agent's purpose, tool surface, recent
session health, and any obvious risks. Use as the first call when
a user asks 'what does X do?' or 'is X healthy?'."

The description should answer **when** to call this tool, not
just what it does.

## Input schema

Standard JSON schema, narrow as possible.

- **`required`** the things the agent actually needs to act —
  don't make everything required if the agent can default.
- **`description`** on every property — the routing LLM uses it
  to know how to fill the slot.
- **`enum`** where the value space is small — much better
  routing than "any string".
- **No nested objects deeper than 2 levels.** Connecting LLMs
  fill nested args inconsistently; flatten where possible.

Example:

```jsonc
{
  "type": "object",
  "properties": {
    "session_id": {
      "type": "string",
      "description": "The session id to debug. Format: s_ABC123.",
    },
    "agent_slug": {
      "type": "string",
      "description": "The slug of the agent owning the session (e.g. 'weekly-digest').",
    },
    "focus": {
      "type": "string",
      "enum": ["failure_cause", "cost", "tool_calls"],
      "description": "What aspect of the session to focus on. Default: failure_cause.",
    },
  },
  "required": ["session_id"],
}
```

## Prompt templates

The template is what becomes the first user message when the tool
is called. Minimal `{{ name }}` interpolation, no logic.

Bad: `"User wants to refund order {{ order_id }}"` — passive,
imprecise.
Better: `"Process this refund request:\n\nOrder: {{ order_id }}\nReason: {{ reason }}"` — direct, structured, the agent reads it as a job.

The template should give the agent enough context to act
immediately. Don't make the agent re-derive what the tool call
already asked for.

## External keys

`external_key_template` (optional) — when set, two calls with
the same rendered key collapse into the same session (instead of
creating two). Useful for:

- Deduping concurrent calls — `"refund:{{ order_id }}"` means two
  refund requests for the same order are one session
- Resuming an in-flight workflow — same key returns the existing
  session

Skip if the tool is genuinely one-shot per call.

## How many tools is too many?

For one agent:

- 0 curated tools (just `ask`) — fine for conversational agents
- 1-3 curated tools — sweet spot for agents with distinct
  workflows
- 4-6 — getting crowded; consider whether to split the agent
- 7+ — almost always a sign the agent should be 2-3 agents
  instead, each with a focused surface

Connecting LLMs get worse at routing as the tool count grows.

## Designing for both `ask` and curated tools

When you have curated tools, **keep `ask` as the escape hatch**.
The connecting client's LLM picks based on the user's intent:

- "refund order 1234" → routes to `request_refund`
- "what's the status of the agent platform?" → routes to `ask`

Your agent's prompt should handle both inputs gracefully. For a
session that opens via a curated tool, the first user message is
the rendered template — your prompt should recognize that shape.
For a session that opens via `ask`, it's a free-form message.

## What to tell the user when designing

When you're helping the user design their MCP surface:

1. **Default to `ask` only.** "You probably don't need curated
   tools — let's start with just `ask`. Add later if specific
   workflows justify it."
2. **If they push back, ask what workflows they envision.** Each
   workflow that fits "user → predictable inputs → known agent
   job" is a candidate curated tool.
3. **Prototype the schema before adding.** Sketch the input
   schema + description + template; show it to the user; only
   then commit.

## Surfacing the connect snippet

After designing the MCP surface, point the user at where the connect
snippet lives — it is **not** a callable tool. The ingress serves it
as a public HTTP route, `GET /agents/<slug>/mcp/connect-info`, which
returns the URL + auth instructions + paste-ready Claude Code / mcp.json
snippets (PostHog Code's Connections tab renders the same thing). So
either send them to the agent's **Connections** tab in PostHog Code or
hand them the connect-info URL. Don't try to set up the client
yourself — the user does that locally.
