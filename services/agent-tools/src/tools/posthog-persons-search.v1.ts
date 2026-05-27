import { defineNativeTool, Type } from '@posthog/agent-shared-v2'

import { getPosthogInternalClient } from '../posthog-client'

export const posthogPersonsSearchV1 = defineNativeTool({
    id: 'posthog.persons.search.v1',
    description: "Search for persons in the team's PostHog project by distinct id, email, or other property.",
    args: Type.Object({
        query: Type.String({ minLength: 1 }),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100, default: 20 })),
    }),
    returns: Type.Object({
        persons: Type.Array(
            Type.Object({
                id: Type.String(),
                distinct_id: Type.String(),
                properties: Type.Record(Type.String(), Type.Unknown()),
            })
        ),
    }),
    requires: { integrations: [], scopes: ['persons:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const client = getPosthogInternalClient()
        const out = await client.searchPersons({
            team_id: ctx.teamId,
            query: args.query,
            limit: args.limit ?? 20,
        })
        return out
    },
})
