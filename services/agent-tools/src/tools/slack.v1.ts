import { defineNativeTool, HttpFetcher, IntegrationCredentials, Type } from '@posthog/agent-shared'

function slackAuth(creds: IntegrationCredentials | undefined): string {
    if (!creds || !creds.access_token) {
        throw new Error('slack integration not connected for this team')
    }
    return creds.access_token
}

async function slackCall(
    http: HttpFetcher,
    token: string,
    method: string,
    body: Record<string, unknown>
): Promise<unknown> {
    const res = await http.fetch(`https://slack.com/api/${method}`, {
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

interface RawSlackMessage {
    ts?: string
    user?: string
    bot_id?: string
    username?: string
    text?: string
    type?: string
    subtype?: string
    thread_ts?: string
    reply_count?: number
}

const SlackMessageSchema = Type.Object({
    ts: Type.String(),
    user: Type.Optional(Type.String()),
    bot_id: Type.Optional(Type.String()),
    username: Type.Optional(Type.String()),
    text: Type.String(),
    subtype: Type.Optional(Type.String()),
    thread_ts: Type.Optional(Type.String()),
    reply_count: Type.Optional(Type.Number()),
})

function projectMessage(m: RawSlackMessage): {
    ts: string
    user?: string
    bot_id?: string
    username?: string
    text: string
    subtype?: string
    thread_ts?: string
    reply_count?: number
} {
    return {
        ts: m.ts ?? '',
        user: m.user,
        bot_id: m.bot_id,
        username: m.username,
        text: m.text ?? '',
        subtype: m.subtype,
        thread_ts: m.thread_ts,
        reply_count: m.reply_count,
    }
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
        const res = (await slackCall(ctx.http, token, 'chat.postMessage', {
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
        await slackCall(ctx.http, token, 'chat.update', { channel: args.channel, ts: args.ts, text: args.text })
        return { ok: true }
    },
})

export const slackReadChannelV1 = defineNativeTool({
    id: '@posthog/slack-read-channel',
    description:
        'Read recent messages from a Slack channel. Returns top-level messages only (use @posthog/slack-read-thread for replies). Paginate with next_cursor; narrow with oldest/latest (slack ts).',
    args: Type.Object({
        team_integration_id: Type.String(),
        channel: Type.String(),
        limit: Type.Optional(Type.Number()),
        oldest: Type.Optional(Type.String()),
        latest: Type.Optional(Type.String()),
        cursor: Type.Optional(Type.String()),
    }),
    returns: Type.Object({
        messages: Type.Array(SlackMessageSchema),
        has_more: Type.Boolean(),
        next_cursor: Type.Optional(Type.String()),
    }),
    requires: { integrations: ['slack'], scopes: ['channels:history', 'groups:history'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackAuth(ctx.integrations[args.team_integration_id])
        const limit = Math.min(Math.max(args.limit ?? 50, 1), 200)
        const body: Record<string, unknown> = { channel: args.channel, limit }
        if (args.oldest) {
            body.oldest = args.oldest
        }
        if (args.latest) {
            body.latest = args.latest
        }
        if (args.cursor) {
            body.cursor = args.cursor
        }
        const res = (await slackCall(ctx.http, token, 'conversations.history', body)) as {
            messages?: RawSlackMessage[]
            has_more?: boolean
            response_metadata?: { next_cursor?: string }
        }
        const nextCursor = res.response_metadata?.next_cursor
        return {
            messages: (res.messages ?? []).map(projectMessage),
            has_more: Boolean(res.has_more),
            next_cursor: nextCursor && nextCursor.length > 0 ? nextCursor : undefined,
        }
    },
})

export const slackReadThreadV1 = defineNativeTool({
    id: '@posthog/slack-read-thread',
    description: 'Read a Slack thread — the parent message plus all replies. thread_ts is the parent message ts.',
    args: Type.Object({
        team_integration_id: Type.String(),
        channel: Type.String(),
        thread_ts: Type.String(),
        limit: Type.Optional(Type.Number()),
        cursor: Type.Optional(Type.String()),
    }),
    returns: Type.Object({
        messages: Type.Array(SlackMessageSchema),
        has_more: Type.Boolean(),
        next_cursor: Type.Optional(Type.String()),
    }),
    requires: { integrations: ['slack'], scopes: ['channels:history', 'groups:history'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackAuth(ctx.integrations[args.team_integration_id])
        const limit = Math.min(Math.max(args.limit ?? 50, 1), 200)
        const body: Record<string, unknown> = {
            channel: args.channel,
            ts: args.thread_ts,
            limit,
        }
        if (args.cursor) {
            body.cursor = args.cursor
        }
        const res = (await slackCall(ctx.http, token, 'conversations.replies', body)) as {
            messages?: RawSlackMessage[]
            has_more?: boolean
            response_metadata?: { next_cursor?: string }
        }
        const nextCursor = res.response_metadata?.next_cursor
        return {
            messages: (res.messages ?? []).map(projectMessage),
            has_more: Boolean(res.has_more),
            next_cursor: nextCursor && nextCursor.length > 0 ? nextCursor : undefined,
        }
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
        await slackCall(ctx.http, token, 'reactions.add', {
            channel: args.channel,
            timestamp: args.ts,
            name: args.name,
        })
        return { ok: true }
    },
})
