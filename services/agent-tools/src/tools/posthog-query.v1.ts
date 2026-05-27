import { z } from 'zod'

import { defineNativeTool } from '@posthog/agent-shared-v2'

import { getPosthogInternalClient } from '../posthog-client'

export const posthogQueryV1 = defineNativeTool({
    id: 'posthog.query.v1',
    description: "Run a HogQL query against the team's PostHog project. Returns rows and column names.",
    args: z.object({
        query: z.string().min(1).describe('HogQL query string'),
    }),
    returns: z.object({
        rows: z.array(z.record(z.string(), z.unknown())),
        columns: z.array(z.string()),
    }),
    requires: { integrations: [], scopes: ['analytics:read'] },
    cost_hint: 'medium',
    async run(args, ctx) {
        const client = getPosthogInternalClient()
        const out = await client.runHogql({ team_id: ctx.teamId, query: args.query })
        ctx.log('info', 'hogql.executed', { query: args.query, row_count: out.rows.length })
        return out
    },
})
