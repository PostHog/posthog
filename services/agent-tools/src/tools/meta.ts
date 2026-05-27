/**
 * Meta tools — control-flow primitives the runner recognizes specially.
 *
 * These don't talk to external systems. The runner intercepts their use:
 *   - ask_for_input  → suspend session, surface a prompt to the user
 *   - end_session    → mark the session completed
 *   - emit_event     → emit a structured event into the team's event stream
 */

import { z } from 'zod'

import { defineNativeTool } from '@posthog/agent-shared-v2'

export const askForInputTool = defineNativeTool({
    id: 'meta.ask_for_input.v1',
    description: 'Suspend the agent and ask the user for input. The session resumes when the user replies.',
    args: z.object({
        prompt: z.string().describe('The question to ask the user.'),
    }),
    returns: z.object({ suspended: z.literal(true) }),
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
    args: z.object({
        summary: z.string().optional(),
    }),
    returns: z.object({ ended: z.literal(true) }),
    requires: { integrations: [], scopes: [] },
    cost_hint: 'cheap',
    async run(_args, _ctx) {
        return { ended: true as const }
    },
})

export const emitEventTool = defineNativeTool({
    id: 'meta.emit_event.v1',
    description: "Emit a structured event into the team's PostHog project.",
    args: z.object({
        event: z.string(),
        distinct_id: z.string(),
        properties: z.record(z.string(), z.unknown()).default({}),
    }),
    returns: z.object({ emitted: z.literal(true) }),
    requires: { integrations: [], scopes: ['events:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        ctx.log('info', 'meta.emit_event', { event: args.event, distinct_id: args.distinct_id })
        return { emitted: true as const }
    },
})
