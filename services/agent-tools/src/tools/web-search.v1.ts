import { defineNativeTool, Type } from '@posthog/agent-shared-v2'

export interface WebSearchProvider {
    search(query: string, limit: number): Promise<Array<{ title: string; url: string; snippet: string }>>
}

let PROVIDER: WebSearchProvider | null = null

export function setWebSearchProvider(p: WebSearchProvider): void {
    PROVIDER = p
}

export const webSearchV1 = defineNativeTool({
    id: '@posthog/web-search',
    description: 'Search the web; returns title, url, and snippet for each result.',
    args: Type.Object({
        query: Type.String({ minLength: 1 }),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 10 })),
    }),
    returns: Type.Object({
        results: Type.Array(
            Type.Object({
                title: Type.String(),
                url: Type.String(),
                snippet: Type.String(),
            })
        ),
    }),
    requires: { integrations: [], scopes: ['web:search'] },
    cost_hint: 'medium',
    async run(args, _ctx) {
        if (!PROVIDER) {
            throw new Error('web.search provider not configured')
        }
        const results = await PROVIDER.search(args.query, args.limit ?? 10)
        return { results }
    },
})
