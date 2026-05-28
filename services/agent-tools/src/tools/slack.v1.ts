import { defineNativeTool, IntegrationCredentials, Type } from '@posthog/agent-shared'

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
    id: '@posthog/slack-post-message',
    description: 'Post a message to a Slack channel or thread.',
    args: Type.Object({
        team_integration_id: Type.String(),
        channel: Type.String(),
        text: Type.String(),
        thread_ts: Type.Optional(Type.String()),
    }),
    returns: Type.Object({
        ts: Type.String(),
        channel: Type.String(),
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
    id: '@posthog/slack-update-message',
    description: 'Edit a previously-posted Slack message.',
    args: Type.Object({
        team_integration_id: Type.String(),
        channel: Type.String(),
        ts: Type.String(),
        text: Type.String(),
    }),
    returns: Type.Object({ ok: Type.Boolean() }),
    requires: { integrations: ['slack'], scopes: ['chat:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackAuth(ctx.integrations[args.team_integration_id])
        await slackCall(token, 'chat.update', { channel: args.channel, ts: args.ts, text: args.text })
        return { ok: true }
    },
})

export const slackReactV1 = defineNativeTool({
    id: '@posthog/slack-react',
    description: 'Add an emoji reaction to a Slack message.',
    args: Type.Object({
        team_integration_id: Type.String(),
        channel: Type.String(),
        ts: Type.String(),
        name: Type.String(),
    }),
    returns: Type.Object({ ok: Type.Boolean() }),
    requires: { integrations: ['slack'], scopes: ['reactions:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackAuth(ctx.integrations[args.team_integration_id])
        await slackCall(token, 'reactions.add', { channel: args.channel, timestamp: args.ts, name: args.name })
        return { ok: true }
    },
})
