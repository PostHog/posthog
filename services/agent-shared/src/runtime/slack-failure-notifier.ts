/**
 * Slack impl of `FailureNotifier`. Posts a sanitized message back to the
 * originating thread when a Slack-triggered session reaches `failed`.
 *
 * Reads channel + thread coordinates off `session.trigger_metadata` (stamped
 * by the slack trigger at enqueue) and resolves the bot token from the
 * application's `encrypted_env` via the shared `SlackSigningSecretResolver`.
 *
 * Failure modes are all silent (logged at warn, returned without throwing) —
 * the dispatcher already does an outer catch but the notifier's own contract
 * is "never throw" so a buggy upgrade can't loop us back into another
 * `session.crashed`.
 */

import { AgentApplication } from '../spec/spec'
import { SLACK_BOT_TOKEN_KEY } from '../spec/trigger-secrets'
import { FailureNotifier, FailureNotifierInput, userFacingMessage } from './failure-notifier'
import { HttpFetcher } from './http-client'
import { SlackSigningSecretResolver } from './slack-secret-resolver'

export interface SlackTriggerMetadata {
    type: 'slack'
    workspace_id: string
    channel: string
    ts: string
    thread_ts: string
}

function isSlackTriggerMetadata(meta: unknown): meta is SlackTriggerMetadata {
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

export interface SlackFailureNotifierDeps {
    http: HttpFetcher
    resolver: SlackSigningSecretResolver
    logger?: {
        warn: (meta: Record<string, unknown>, msg: string) => void
        info?: (meta: Record<string, unknown>, msg: string) => void
    }
}

export class SlackFailureNotifier implements FailureNotifier {
    constructor(private readonly deps: SlackFailureNotifierDeps) {}

    async notify(input: FailureNotifierInput): Promise<void> {
        const meta = input.session.trigger_metadata
        if (!isSlackTriggerMetadata(meta)) {
            return
        }
        const token = await this.resolveTokenSafely(input.application, input.session.id)
        if (!token) {
            return
        }
        const text = userFacingMessage(input.category)
        try {
            const res = await this.deps.http.fetch('https://slack.com/api/chat.postMessage', {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${token}`,
                    'Content-Type': 'application/json; charset=utf-8',
                },
                body: JSON.stringify({
                    channel: meta.channel,
                    thread_ts: meta.thread_ts,
                    text,
                }),
            })
            await this.logSlackResult(res, input.session.id, meta)
        } catch (err) {
            this.deps.logger?.warn(
                {
                    session_id: input.session.id,
                    channel: meta.channel,
                    err: err instanceof Error ? err.message : String(err),
                },
                'slack_failure_notifier_post_threw'
            )
        }
    }

    private async resolveTokenSafely(application: AgentApplication, sessionId: string): Promise<string | null> {
        try {
            const token = await this.deps.resolver.resolve(SLACK_BOT_TOKEN_KEY, application)
            if (!token) {
                this.deps.logger?.warn(
                    { session_id: sessionId, application_id: application.id },
                    'slack_failure_notifier_no_bot_token'
                )
            }
            return token
        } catch (err) {
            this.deps.logger?.warn(
                {
                    session_id: sessionId,
                    application_id: application.id,
                    err: err instanceof Error ? err.message : String(err),
                },
                'slack_failure_notifier_token_resolve_threw'
            )
            return null
        }
    }

    private async logSlackResult(res: Response, sessionId: string, meta: SlackTriggerMetadata): Promise<void> {
        let body: { ok?: boolean; error?: string } = {}
        try {
            body = (await res.json()) as { ok?: boolean; error?: string }
        } catch {
            // Non-JSON — log + return.
        }
        const fields = {
            session_id: sessionId,
            channel: meta.channel,
            thread_ts: meta.thread_ts,
            status: res.status,
            slack_error: body.error ?? null,
        }
        if (!res.ok || body.ok === false) {
            this.deps.logger?.warn(fields, 'slack_failure_notifier_post_failed')
            return
        }
        this.deps.logger?.info?.(fields, 'slack_failure_notifier_posted')
    }
}
