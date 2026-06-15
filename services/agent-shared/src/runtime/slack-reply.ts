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

export interface SlackStatusReporterDeps {
    http: HttpFetcher
    token: string | undefined
    channel: string
    thread_ts: string
    sessionId?: string
    logger?: SlackReplyLogger
    /** Min gap between chat.update calls — Slack rate-limits updates. Default 1000ms. */
    minUpdateIntervalMs?: number
    /** Injectable clock for tests. Default Date.now. */
    now?: () => number
}

/**
 * A single ephemeral-feeling "working on it" status message in the thread. The
 * runner posts it while a turn is in flight, updates it as tools run, and
 * removes it the moment a real reply lands (re-posting on the next turn) so the
 * latest visible message is always the agent's actual answer. Never throws.
 *
 * Not a true Slack ephemeral (those need a response_url and can't be edited) —
 * a normal message we post / chat.update / chat.delete, which works from an
 * event-triggered session.
 */
export class SlackStatusReporter {
    private ts: string | null = null
    private lastText: string | null = null
    private lastUpdateMs = 0

    constructor(private readonly deps: SlackStatusReporterDeps) {}

    /** Post the status message if it isn't already shown. */
    async start(text: string): Promise<void> {
        if (this.ts || !this.deps.token) {
            return
        }
        const res = await this.call('chat.postMessage', {
            channel: this.deps.channel,
            thread_ts: this.deps.thread_ts,
            text,
        })
        if (res?.ts) {
            this.ts = res.ts
            this.lastText = text
            this.lastUpdateMs = this.clock()
        }
    }

    /** Edit the status text. Throttled + best-effort; no-op if not shown. */
    async update(text: string): Promise<void> {
        if (!this.ts || !this.deps.token || text === this.lastText) {
            return
        }
        const now = this.clock()
        if (now - this.lastUpdateMs < (this.deps.minUpdateIntervalMs ?? 1000)) {
            return
        }
        this.lastText = text
        this.lastUpdateMs = now
        await this.call('chat.update', { channel: this.deps.channel, ts: this.ts, text })
    }

    /** Remove the status message. Idempotent. */
    async clear(): Promise<void> {
        if (!this.ts || !this.deps.token) {
            return
        }
        const ts = this.ts
        this.ts = null
        await this.call('chat.delete', { channel: this.deps.channel, ts })
    }

    private clock(): number {
        return (this.deps.now ?? Date.now)()
    }

    private async call(method: string, body: Record<string, unknown>): Promise<{ ok?: boolean; ts?: string } | null> {
        try {
            const res = await this.deps.http.fetch(`https://slack.com/api/${method}`, {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${this.deps.token}`,
                    'Content-Type': 'application/json; charset=utf-8',
                },
                body: JSON.stringify(body),
            })
            let parsed: { ok?: boolean; ts?: string; error?: string } = {}
            try {
                parsed = (await res.json()) as { ok?: boolean; ts?: string; error?: string }
            } catch {
                // Non-JSON — treated as a failure via res.ok below.
            }
            if (!res.ok || parsed.ok === false) {
                this.deps.logger?.warn(
                    {
                        session_id: this.deps.sessionId,
                        channel: this.deps.channel,
                        method,
                        status: res.status,
                        slack_error: parsed.error ?? null,
                    },
                    'slack_status_failed'
                )
                return null
            }
            return parsed
        } catch (err) {
            this.deps.logger?.warn(
                {
                    session_id: this.deps.sessionId,
                    channel: this.deps.channel,
                    method,
                    err: err instanceof Error ? err.message : String(err),
                },
                'slack_status_threw'
            )
            return null
        }
    }
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
