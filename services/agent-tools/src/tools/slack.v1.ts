import { z } from 'zod'

import { defineNativeTool, IntegrationCredentials } from '@posthog/agent-shared-v2'

function slackAuth(creds: IntegrationCredentials | undefined): string {
    if (!creds || !creds.access_token) {
        throw new Error('slack integration not connected for this team')
    }
    return creds.access_token
}

async function slackCall(token: string, method: string, body: Record<string, unknown>): Promise<unknown> {
    const res = await fetch(`https://slack.com/api/${method}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json; charset=utf-8',
            Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        throw new Error(`slack.${method} HTTP ${res.status}`)
    }
    const j = (await res.json()) as { ok: boolean; error?: string }
    if (!j.ok) {
        throw new Error(`slack.${method} error: ${j.error ?? 'unknown'}`)
    }
    return j
}

export const slackPostMessageV1 = defineNativeTool({
    id: 'slack.post_message.v1',
    description: 'Post a message to a Slack channel or thread.',
    args: z.object({
        team_integration_id: z.string(),
        channel: z.string(),
        text: z.string(),
        thread_ts: z.string().optional(),
    }),
    returns: z.object({
        ts: z.string(),
        channel: z.string(),
    }),
    requires: { integrations: ['slack'], scopes: ['chat:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackAuth(ctx.integrations[args.team_integration_id])
        const res = (await slackCall(token, 'chat.postMessage', {
            channel: args.channel,
            text: args.text,
            thread_ts: args.thread_ts,
        })) as { ts: string; channel: string }
        return { ts: res.ts, channel: res.channel }
    },
})

export const slackUpdateMessageV1 = defineNativeTool({
    id: 'slack.update_message.v1',
    description: 'Edit a previously-posted Slack message.',
    args: z.object({
        team_integration_id: z.string(),
        channel: z.string(),
        ts: z.string(),
        text: z.string(),
    }),
    returns: z.object({ ok: z.boolean() }),
    requires: { integrations: ['slack'], scopes: ['chat:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackAuth(ctx.integrations[args.team_integration_id])
        await slackCall(token, 'chat.update', { channel: args.channel, ts: args.ts, text: args.text })
        return { ok: true }
    },
})

export const slackReactV1 = defineNativeTool({
    id: 'slack.react.v1',
    description: 'Add an emoji reaction to a Slack message.',
    args: z.object({
        team_integration_id: z.string(),
        channel: z.string(),
        ts: z.string(),
        name: z.string(),
    }),
    returns: z.object({ ok: z.boolean() }),
    requires: { integrations: ['slack'], scopes: ['reactions:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackAuth(ctx.integrations[args.team_integration_id])
        await slackCall(token, 'reactions.add', { channel: args.channel, timestamp: args.ts, name: args.name })
        return { ok: true }
    },
})
