/**
 * Meta tools — control-flow primitives the runner recognizes specially.
 *
 * These don't talk to external systems. The runner intercepts their use:
 *   - ask_for_input  → suspend session, surface a prompt to the user
 *   - end_session    → mark the session completed
 *   - emit_event     → emit a structured event into the team's event stream
 */

import { defineNativeTool, Type } from '@posthog/agent-shared-v2'

export const askForInputTool = defineNativeTool({
    id: 'meta.ask_for_input.v1',
    description: 'Suspend the agent and ask the user for input. The session resumes when the user replies.',
    args: Type.Object({
        prompt: Type.String({ description: 'The question to ask the user.' }),
    }),
    returns: Type.Object({ suspended: Type.Literal(true) }),
    requires: { integrations: [], scopes: [] },
    cost_hint: 'cheap',
    async run(_args, _ctx) {
        // Runner intercepts this — never actually called.
        return { suspended: true as const }
    },
})

export const endSessionTool = defineNativeTool({
    id: 'meta.end_session.v1',
    description: 'End the agent session. Optionally include a final summary.',
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
    id: 'meta.emit_event.v1',
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
