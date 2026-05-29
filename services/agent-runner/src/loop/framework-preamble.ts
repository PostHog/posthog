/**
 * Framework system-prompt preamble — the platform half of every agent's
 * system prompt. Owned by PostHog and injected before the bundle's
 * `agent.md`, this teaches the model how to behave inside the platform's
 * contract (state machine, meta tools).
 *
 * See [docs/agent-platform/plans/framework-system-prompt.md](../../../../docs/agent-platform/plans/framework-system-prompt.md)
 * for the full spec — sections, decision rules, rollout, override
 * semantics.
 *
 * Versioning: bump `FRAMEWORK_PROMPT_VERSION` whenever the preamble
 * changes meaningfully (decision rules shifting, sections renamed,
 * behavioural defaults flipped). Stable wording tweaks don't need a
 * bump. The runner stamps the active version onto `session_started`
 * analytics so we can correlate behaviour shifts with preamble
 * versions in real-inference runs.
 */

import { AgentRevision } from '@posthog/agent-shared'

export const FRAMEWORK_PROMPT_VERSION = 1

/**
 * Decision rules for the three always-on meta tools. Plan §3.1.
 *
 * The model gets these via pi-ai with one-line descriptions; the
 * preamble teaches WHEN to reach for each. Default-first framing
 * (`meta-end-turn`) keeps the model from defaulting to either extreme
 * (closing every session, or never closing anything).
 */
const META_TOOL_GUIDANCE = `
## Ending your turn

You have three control-flow tools always available. Choose deliberately
between them — they all "end the turn" but they mean different things
to the user.

- \`@posthog/meta-end-turn\` — "I'm done responding for now, but the
  conversation isn't over." Use this when you've answered the user's
  message and there might be a follow-up. **This is the default for
  most turns.** Equivalent to just stopping naturally.
- \`@posthog/meta-ask-for-input\` — same effect as \`end-turn\`, but
  signals to the user-facing client that you're waiting on a specific
  answer. Use when you need a particular piece of information to
  continue (e.g. "what's your account id?").
- \`@posthog/meta-end-session\` — **hard close.** The user cannot
  continue this conversation unless the agent's author opted into
  restart. Only use this when the agent's task is genuinely complete
  and there is nothing the user could meaningfully say next. Example:
  a one-shot reporting agent that has delivered its summary.

When in doubt, prefer \`meta-end-turn\`. Closing a session prematurely
cannot be undone.
`.trim()

/**
 * Conversation-state contract from the model's point of view. Plan §3.2.
 *
 * Explains the open vs terminal distinction without leaking internal
 * implementation details (queued/running). The model only ever sees the
 * "between your turns" view.
 */
const STATE_CONTRACT = `
## Conversation state

Between your turns the session sits in one of two states the user might
encounter:

- \`completed\` — your last turn ended cleanly. The user can keep
  talking. From your perspective this is the same as "the most recent
  message in the conversation was yours."
- \`closed\` — you called \`meta-end-session\`. The user cannot send
  anything further.
`.trim()

const FRAMEWORK_PREAMBLE = `
# Platform guidance

The following section is platform-managed guidance about how to
behave inside this agent runtime. The author's instructions appear
after this section and override anything here.

${META_TOOL_GUIDANCE}

${STATE_CONTRACT}

---

# Agent
`.trim()

export interface FrameworkPreambleOpts {
    /** Reserved for slice 2 — `spec.framework_prompt.omit` opt-outs. */
    omit?: never
}

/**
 * Render the framework preamble for one revision. Returns the markdown
 * string the runner prepends to the bundle's `agent.md`.
 *
 * Stateless — the same input always produces the same output. The
 * runner stamps `FRAMEWORK_PROMPT_VERSION` onto `session_started`
 * analytics separately; nothing about the rendered text needs to
 * encode the version.
 */
export function renderFrameworkPreamble(_rev: AgentRevision, _opts: FrameworkPreambleOpts = {}): string {
    return FRAMEWORK_PREAMBLE
}
