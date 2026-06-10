# Skill — working outside the console

How to be useful when there is no UI — load when `client.kind` is
`mcp:*` (Claude Code, Cursor, MCP Inspector) or any other shape
that doesn't declare `@posthog/ui/focus` in its handles. Without
client tools, every navigation has to happen in text.

## What changes vs the console

| Capability                               | Console                                    | MCP / IDE                                   |
| ---------------------------------------- | ------------------------------------------ | ------------------------------------------- |
| User sees the artifact you're working on | Yes — `@posthog/ui/focus` drives the panel | No — the user sees only your text           |
| User can context-switch by clicking      | Yes — they can wander                      | No — the conversation IS the navigation     |
| Status notifications                     | `@posthog/ui/toast`                        | A short line in the chat                    |
| Streaming partial output                 | Sometimes rendered nicely                  | Usually rendered as plain text              |
| Approval requests                        | Inline buttons in the dock                 | A text instruction to take action elsewhere |

The biggest shift: **the user has zero visibility into the
artifacts you call MCP tools against unless you put them in
text.** A `agent-applications-revisions-bundle-retrieve` that
returns 5 files in the console can be opened in the panel; over
MCP, you have to summarize.

## Compensating moves

### 1. Lead with explicit references

Every artifact you touch gets named in text. Slug, revision id,
file path. The user copy-pastes these into their own tools (a
browser at app.posthog.com, a curl) if they want to verify.

> Reading `weekly-digest` (id `app_abc123`), live revision
> `r_xyz789`, file `agent.md` (87 lines, last edited 2026-05-12).

vs the console-friendly equivalent:

> Opening weekly-digest's live revision in the panel.

The MCP version pays for the extra words; the value is the user
can act on the references without further round-trips.

### 2. Inline summaries instead of "see the panel"

When the user would have looked at the read panel, instead
include the summary in your message. Trade tokens for context.

> System prompt summary (3 sections, 87 lines total):
>
> - Identity (1-12): "You are the weekly-digest agent…"
> - Job (13-50): walks through the digest flow, mentions
>   $pageview / $autocapture
> - Tone (51-87): casual, asks for ack at the end
>
> Full file (paste to read)?
>
> ```text
> [contents on request]
> ```

Don't dump the file unprompted — offer to.

### 3. Tighter sequencing

In the console, you can fire multiple MCP calls in one turn
because the user is watching the panel transitions. Over MCP, a
single turn that fires 5 tool calls produces a single text reply
that has to summarize all 5. Prefer:

- 1-3 tool calls per turn
- A clear handoff back to the user between turns
- "Want me to also pull X?" as a question, not as another tool
  call

## Detecting that you're outside the console

Look at the session-start info event. It includes `client.kind`.

- `agent-console@1`, `agent-console-dock@*` → console
- `mcp:claude-code`, `mcp:cursor`, `mcp:inspector`, `mcp:*` → IDE
- `slack-adapter@*` → Slack (use the slack flow instead, not this
  skill — but slack isn't in v0 spec, so this won't fire today)
- `unknown` or missing → assume MCP — text-only is the safer
  default

You can also tell from your tool surface: if `@posthog/ui/focus`
is missing, you're not in the console.

## MCP-specific affordances you DO have

The MCP transport exposes things the console doesn't always:

- **The `Mcp-Session-Id` header** — the connecting MCP client's
  session id. Multiple chat-trigger sessions from the same MCP
  connection share this. Useful when the user says "what was
  that other session we just looked at?" — you can list resources
  filtered by their MCP connection.
- **`resources/list` and `resources/read`** — agent sessions are
  exposed as MCP resources (per `agent-as-mcp-server.md` §3).
  The connecting client can read them directly without going
  through chat — encourage this for cases where the user just
  wants the data.
- **Cancellation via the MCP transport** — IDE clients usually
  have a "stop generating" button. The runner gets the cancel
  signal cleanly.

## When the user asks for something only the console can do

E.g. "show me the file tree visually" or "click that button". Be
direct:

> The file tree view is a console-only thing — you're connected
> via MCP. I can list the file paths in text instead:
>
> - agent.md
> - skills/triage-playbook.md
> - skills/slack-thread-protocol.md
> - tests/happy-path.json
>
> Or, if you want the visual view, open the console at
> console.agents.posthog.com → weekly-digest → bundle.

Don't pretend you can drive a UI that isn't there.

## Pasting code over MCP

IDE clients render code blocks well. Use them for:

- File contents the user asked to read
- Spec JSON snippets when explaining a structural concept
- Tool call arguments when explaining why a call failed

Keep them short. A 200-line `agent.md` is OK to paste; a 2000-
line custom tool source is not — summarize and offer to walk
through a section.

## The slack mode (when it exists)

Not in v0. When the agent grows a `slack` trigger and is invoked
in a Slack channel, the rules from `working-outside-the-console`
mostly apply (text-only) but with Slack-specific formatting:

- Use Slack markdown (`*bold*`, `_italic_`, code with single
  backticks)
- Stay terse — channel signal-to-noise matters
- Always thread your replies under the triggering message
- Don't paste long bundle contents in channel — link to the
  console / DM instead

Until the slack trigger lands, you won't see this client kind.
