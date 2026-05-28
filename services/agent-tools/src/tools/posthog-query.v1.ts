import { defineNativeTool, Type } from '@posthog/agent-shared-v2'

import { getPosthogInternalClient } from '../posthog-client'

export const posthogQueryV1 = defineNativeTool({
    id: '@posthog/query',
    description: "Run a HogQL query against the team's PostHog project. Returns rows and column names.",
    args: Type.Object({
        query: Type.String({ minLength: 1, description: 'HogQL query string' }),
    }),
    returns: Type.Object({
        rows: Type.Array(Type.Record(Type.String(), Type.Unknown())),
        columns: Type.Array(Type.String()),
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
