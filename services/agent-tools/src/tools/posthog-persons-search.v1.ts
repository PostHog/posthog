import { z } from 'zod'

import { defineNativeTool } from '@posthog/agent-shared-v2'

import { getPosthogInternalClient } from '../posthog-client'

export const posthogPersonsSearchV1 = defineNativeTool({
    id: 'posthog.persons.search.v1',
    description: "Search for persons in the team's PostHog project by distinct id, email, or other property.",
    args: z.object({
        query: z.string().min(1),
        limit: z.number().int().positive().max(100).default(20),
    }),
    returns: z.object({
        persons: z.array(
            z.object({
                id: z.string(),
                distinct_id: z.string(),
                properties: z.record(z.string(), z.unknown()),
            })
        ),
    }),
    requires: { integrations: [], scopes: ['persons:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const client = getPosthogInternalClient()
        const out = await client.searchPersons({ team_id: ctx.teamId, query: args.query, limit: args.limit })
        return out
    },
})
