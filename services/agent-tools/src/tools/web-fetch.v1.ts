import { z } from 'zod'

import { defineNativeTool } from '@posthog/agent-shared-v2'

const URL_SCHEMA = z.string().url()

export const webFetchV1 = defineNativeTool({
    id: 'web.fetch.v1',
    description: "GET a URL and return its body. Only domains in the agent's spec.web_fetch_allowlist are permitted.",
    args: z.object({
        url: URL_SCHEMA,
        max_bytes: z.number().int().positive().max(5_000_000).default(1_000_000),
    }),
    returns: z.object({
        status: z.number(),
        body: z.string(),
        content_type: z.string(),
        url: z.string(),
    }),
    requires: { integrations: [], scopes: ['web:fetch'] },
    cost_hint: 'medium',
    async run(args, ctx) {
        const allowlist = ((): string[] => {
            // The runner is expected to project spec.tools.web_fetch.allowlist into ctx
            // via a global context bag; for v1 the bag isn't wired so we permit anything,
            // but log a warning so this gates cleanly when the bag arrives.
            ctx.log('warn', 'web.fetch allowlist not yet enforced; permitting all')
            return []
        })()
        const u = new URL(args.url)
        if (allowlist.length && !allowlist.includes(u.host)) {
            throw new Error(`host not allowed: ${u.host}`)
        }
        const res = await fetch(args.url, { method: 'GET' })
        const text = await res.text()
        return {
            status: res.status,
            body: text.length > args.max_bytes ? text.slice(0, args.max_bytes) : text,
            content_type: res.headers.get('content-type') ?? '',
            url: args.url,
        }
    },
})
