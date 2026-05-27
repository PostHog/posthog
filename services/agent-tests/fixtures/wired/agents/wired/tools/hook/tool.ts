import { defineTool, z } from '@posthog/ass'

/**
 * Webhook tool with a secret URL. The whole point: `ctx.secrets.ref()`
 * yields a nonce, the egress proxy in the sandbox substitutes the real
 * URL before the request leaves the container. The tool code, the model,
 * and every log entry along the way only ever hold the nonce.
 */
export default defineTool({
    id: 'hook',
    version: 1,
    description: 'Deliver a titled message to a preconfigured webhook URL.',
    inputs: [
        {
            id: 'WEBHOOK_URL',
            secret: true,
            description: 'Full incoming-webhook URL. The URL itself is the credential.',
        },
    ],
    actions: {
        deliver: {
            description: 'POST a title+body to the configured webhook.',
            args: z.object({
                title: z.string(),
                body: z.string(),
            }),
            returns: z.object({
                status: z.number(),
                delivered: z.boolean(),
            }),
            async run({ title, body }, ctx) {
                const res = await ctx.http.fetch(ctx.secrets.ref('WEBHOOK_URL'), {
                    method: 'POST',
                    body: { title, body, text: `*${title}*\n${body}` },
                })
                return {
                    status: res.status,
                    delivered: res.status >= 200 && res.status < 300,
                }
            },
        },
    },
})
