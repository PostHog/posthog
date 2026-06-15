/**
 * Slack reply relay: posts an agent's finalized assistant message into its
 * originating Slack thread. The platform owns Slack delivery for slack-triggered
 * sessions — the model just replies in natural language and the runner relays
 * each completed message here, mirroring how the chat trigger streams text back
 * to the console. `@posthog/slack-post-message` stays available for advanced
 * sends (Block Kit, other channels, DMs, edits).
 *
 * Never throws — a Slack hiccup must not break the agent loop. Failures log at
 * warn and return false.
 */

import { HttpFetcher } from './http-client'

export interface SlackTriggerMetadata {
    type: 'slack'
    workspace_id: string
    channel: string
    ts: string
    thread_ts: string
}

export function isSlackTriggerMetadata(meta: unknown): meta is SlackTriggerMetadata {
    if (!meta || typeof meta !== 'object') {
        return false
    }
    const m = meta as Record<string, unknown>
    return (
        m.type === 'slack' &&
        typeof m.channel === 'string' &&
        typeof m.thread_ts === 'string' &&
        m.channel.length > 0 &&
        m.thread_ts.length > 0
    )
}

/** Join the text blocks of an assistant message into one Slack message body. */
export function slackTextFromContent(content: ReadonlyArray<{ type: string; text?: string }>): string {
    return content
        .filter((b): b is { type: string; text: string } => b.type === 'text' && typeof b.text === 'string')
        .map((b) => b.text)
        .join('\n\n')
        .trim()
}

export interface SlackReplyLogger {
    warn: (meta: Record<string, unknown>, msg: string) => void
    info?: (meta: Record<string, unknown>, msg: string) => void
}

export interface PostSlackReplyOpts {
    token: string | undefined
    channel: string
    thread_ts: string
    text: string
    sessionId?: string
    logger?: SlackReplyLogger
}

export async function postSlackReply(http: HttpFetcher, opts: PostSlackReplyOpts): Promise<boolean> {
    const text = opts.text.trim()
    if (!text) {
        return false
    }
    if (!opts.token) {
        opts.logger?.warn({ session_id: opts.sessionId, channel: opts.channel }, 'slack_reply_no_bot_token')
        return false
    }
    try {
        const res = await http.fetch('https://slack.com/api/chat.postMessage', {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${opts.token}`,
                'Content-Type': 'application/json; charset=utf-8',
            },
            body: JSON.stringify({ channel: opts.channel, thread_ts: opts.thread_ts, text }),
        })
        let body: { ok?: boolean; error?: string } = {}
        try {
            body = (await res.json()) as { ok?: boolean; error?: string }
        } catch {
            // Non-JSON response — fall through to the res.ok check below.
        }
        if (!res.ok || body.ok === false) {
            opts.logger?.warn(
                {
                    session_id: opts.sessionId,
                    channel: opts.channel,
                    thread_ts: opts.thread_ts,
                    status: res.status,
                    slack_error: body.error ?? null,
                },
                'slack_reply_post_failed'
            )
            return false
        }
        return true
    } catch (err) {
        opts.logger?.warn(
            {
                session_id: opts.sessionId,
                channel: opts.channel,
                err: err instanceof Error ? err.message : String(err),
            },
            'slack_reply_post_threw'
        )
        return false
    }
}
