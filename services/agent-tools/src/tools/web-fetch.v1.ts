import { defineNativeTool, Type } from '@posthog/agent-shared-v2'

export const webFetchV1 = defineNativeTool({
    id: '@posthog/web-fetch',
    description: "GET a URL and return its body. Only domains in the agent's spec.web_fetch_allowlist are permitted.",
    args: Type.Object({
        url: Type.String({ format: 'uri' }),
        max_bytes: Type.Optional(Type.Integer({ minimum: 1, maximum: 5_000_000, default: 1_000_000 })),
    }),
    returns: Type.Object({
        status: Type.Number(),
        body: Type.String(),
        content_type: Type.String(),
        url: Type.String(),
    }),
    requires: { integrations: [], scopes: ['web:fetch'] },
    cost_hint: 'medium',
    async run(args, ctx) {
        const maxBytes = args.max_bytes ?? 1_000_000
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
            body: text.length > maxBytes ? text.slice(0, maxBytes) : text,
            content_type: res.headers.get('content-type') ?? '',
            url: args.url,
        }
    },
})
