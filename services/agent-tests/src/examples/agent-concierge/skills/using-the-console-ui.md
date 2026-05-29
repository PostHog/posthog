# Skill — using the console UI

How to drive the agent console's read panel while you work, so
the user always sees what you're working on. Load when
`client.kind` starts with `agent-console`.

## The two client tools you have

| Tool                | What it does                                                                            | When to call                                                                          |
| ------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `@posthog/ui/focus` | Navigates the read panel to a specific resource (file, revision, session, spec section) | Whenever you start working on something — the user should see what you see            |
| `@posthog/ui/toast` | Surfaces a transient status notification in the console                                 | Sparingly — for long-running tool calls, or to flag something the user should look at |

Both are no-ops if the client doesn't handle them; the runner
hides them from your tool surface. If they're in your tool list,
the console is on the other end.

## `@posthog/ui/focus` etiquette

**Call it before the tool call that operates on the resource**,
not after. The user wants the panel to load _as_ you start
working, not after the work is done.

Sequence:

1. Tell the user what you're about to do (one line)
2. `@posthog/ui/focus` to the resource
3. Make the actual MCP / native tool call(s)
4. Report back

The four `focus.kind` values and when to use each:

| `kind`         | Args                                                                  | Use when                                              |
| -------------- | --------------------------------------------------------------------- | ----------------------------------------------------- |
| `file`         | `{ path: "skills/research.md" }`                                      | Reading or editing a specific bundle file             |
| `revision`     | `{ revision_id: "r_abc123" }`                                         | Reading or editing a revision's spec / bundle overall |
| `session`      | `{ session_id: "s_xyz789" }`                                          | Debugging or watching a session                       |
| `spec_section` | `{ section: "tools" / "skills" / "triggers" / "secrets" / "limits" }` | Discussing a specific part of the spec                |

For a multi-file flow (e.g. inspecting `agent.md` then a skill
then the live session), call focus **before each transition**.
Don't focus once and assume the user followed your text-based
navigation.

## Handle the focus result

`@posthog/ui/focus` returns either:

- `{ focused: true, kind: ..., ... }` — the panel loaded; the
  user saw it
- `{ focused: false, reason: "user_paused_follow" }` — the user
  has "Follow the agent" turned off; the panel didn't change

When `focused: false`, **adapt**:

- Spell out the resource path in text (`"see skills/research.md
in the bundle"`)
- Don't keep firing focus events — they're being ignored on
  purpose
- Note it once ("Follow-mode is off, so I'll narrate paths instead.")

When `focused: true`, **keep your text concise** — the user can
see what you see, so don't re-describe it. "Read `agent.md`,
turn 1 makes the agent skip the slack post on weekends" is
enough; don't paste the whole file.

## `@posthog/ui/toast` etiquette

Toasts are intrusive. Use them only for:

- **Long-running work** the user should know about: "Running 5
  test cases — this will take ~30s"
- **State changes outside their current view**: "Revision r_new
  promoted to live"
- **Errors that need their attention** but don't block the
  conversation: "Slack integration token expired — re-auth at
  <link>"

Don't toast for:

- Status updates that fit in the chat ("Reading agent now…")
- Progress on a quick call (anything under 5s)
- Things the user is actively watching (they don't need a toast
  about something they can see)

Toasts are silent for the model — they're a UI side effect, not
a tool result you should react to.

## When the user steers via the read panel

The console lets the user click around the read panel
independently. If the user says "I just opened revisions, can
you compare r_old and r_new?", they have navigated themselves —
you can pick up from there without focusing first. But still
focus before YOUR next action.

## Combining focus + acknowledgement

Pattern: one short text line + one focus call + the actual work,
all in the same turn.

Example:

> Opening `weekly-digest`'s live revision, pulling its spec +
> system prompt.
>
> [calls `@posthog/ui/focus` with `{ kind: 'revision',
> > revision_id: 'r_live123' }`]
>
> [calls `agent-applications-revisions-retrieve`]
> [calls `agent-applications-revisions-system-prompt`]
>
> Spec is 4 tools, 3 skills, cron trigger every Monday 09:00.
> Want me to walk through the skills, or jump to recent sessions?

The user's experience: text appears, panel transitions to the
revision view, a moment later the chat shows the summary. Three
beats, all in one turn.

## When NOT to focus

- The user just asked you to summarize without context-switching
  ("just give me the slug list, don't open anything")
- The thing you're looking at isn't a UI-representable resource
  (e.g. a transient computation, an in-memory inference)
- You're mid-debug and the user has explicitly turned follow-mode
  off — respect it

## Errors from focus

If focus returns `client_tool_unsupported` (unexpected — should
have been hidden from your surface), behave as if you got
`focused: false`. Don't crash; fall back to text narration. This
shouldn't happen, but a buggy console version might.

## The "screen-sharing" mental model

Treat `@posthog/ui/focus` as moving a cursor on a shared screen.
Every action you take, the user should be able to see _where_
you took it. The chat is the audio narration; the read panel is
the screen. Together they make the whole interaction legible —
without focus, the chat reads like talking to someone whose
screen is off.
