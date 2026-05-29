/**
 * Meta tools — control-flow primitives the runner recognizes specially.
 *
 * These don't talk to external systems. The runner intercepts their use:
 *   - end_turn       → finish the current turn; session stays `completed` (open)
 *   - ask_for_input  → focus hint event for the UI; session stays `completed`
 *   - end_session    → hard close; session goes to `closed` (terminal unless
 *                      the trigger config sets `allow_restart`)
 *   - emit_event     → emit a structured event into the team's event stream
 *
 * The default end-of-turn behavior (model naturally stops with `stopReason
 * = 'stop'`) is equivalent to calling `end_turn` — agents that don't call
 * any meta tool still land in `completed` (open). `end_turn` exists so
 * authors can pair it explicitly with `end_session` in the system prompt:
 * "use end_turn when you're done responding; only use end_session if the
 * agent's task is irreversibly finished."
 *
 * See docs/agent-platform/plans/_TODO.md for the system-prompt content
 * that teaches the model when to use each.
 */

import { defineNativeTool, Type } from '@posthog/agent-shared'

export const endTurnTool = defineNativeTool({
    id: '@posthog/meta-end-turn',
    description:
        'Finish the current turn. The user can still send follow-up messages — this is the default polite stop. Use this whenever you have nothing more to add for now, unless the agent task is truly complete (then use meta-end-session instead).',
    args: Type.Object({}),
    returns: Type.Object({ ended_turn: Type.Literal(true) }),
    requires: { integrations: [], scopes: [] },
    cost_hint: 'cheap',
    async run(_args, _ctx) {
        // Runner intercepts this — never actually called.
        return { ended_turn: true as const }
    },
})

export const askForInputTool = defineNativeTool({
    id: '@posthog/meta-ask-for-input',
    description:
        'Tell the user-facing client that the next user message should answer a specific question. Emits a focus-hint event; functionally equivalent to ending the turn (the session stays open for any follow-up). The `prompt` is what the client surfaces.',
    args: Type.Object({
        prompt: Type.String({ description: 'The question to surface to the user.' }),
    }),
    returns: Type.Object({ asked: Type.Literal(true) }),
    requires: { integrations: [], scopes: [] },
    cost_hint: 'cheap',
    async run(_args, _ctx) {
        // Runner intercepts this — never actually called.
        return { asked: true as const }
    },
})

export const endSessionTool = defineNativeTool({
    id: '@posthog/meta-end-session',
    description:
        'Hard close the agent session. The user can NOT send further messages unless the agent is configured with allow_restart. Only use this when the agent task is irreversibly complete; otherwise prefer meta-end-turn.',
    args: Type.Object({
        summary: Type.Optional(Type.String()),
    }),
    returns: Type.Object({ ended: Type.Literal(true) }),
    requires: { integrations: [], scopes: [] },
    cost_hint: 'cheap',
    async run(_args, _ctx) {
        return { ended: true as const }
    },
})

export const emitEventTool = defineNativeTool({
    id: '@posthog/meta-emit-event',
    description: "Emit a structured event into the team's PostHog project.",
    args: Type.Object({
        event: Type.String(),
        distinct_id: Type.String(),
        properties: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
    }),
    returns: Type.Object({ emitted: Type.Literal(true) }),
    requires: { integrations: [], scopes: ['events:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        ctx.log('info', 'meta.emit_event', { event: args.event, distinct_id: args.distinct_id })
        return { emitted: true as const }
    },
})
