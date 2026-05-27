import { z } from 'zod'

import { defineNativeTool } from '@posthog/agent-shared-v2'

export interface WebSearchProvider {
    search(query: string, limit: number): Promise<Array<{ title: string; url: string; snippet: string }>>
}

let PROVIDER: WebSearchProvider | null = null

export function setWebSearchProvider(p: WebSearchProvider): void {
    PROVIDER = p
}

export const webSearchV1 = defineNativeTool({
    id: 'web.search.v1',
    description: 'Search the web; returns title, url, and snippet for each result.',
    args: z.object({
        query: z.string().min(1),
        limit: z.number().int().positive().max(20).default(10),
    }),
    returns: z.object({
        results: z.array(
            z.object({
                title: z.string(),
                url: z.string(),
                snippet: z.string(),
            })
        ),
    }),
    requires: { integrations: [], scopes: ['web:search'] },
    cost_hint: 'medium',
    async run(args, _ctx) {
        if (!PROVIDER) {
            throw new Error('web.search provider not configured')
        }
        const results = await PROVIDER.search(args.query, args.limit)
        return { results }
    },
})
