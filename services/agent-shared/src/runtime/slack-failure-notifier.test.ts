import { describe, expect, it, vi } from 'vitest'

import { AgentApplication, AgentSession } from '../spec/spec'
import { HttpFetcher } from './http-client'
import { SlackFailureNotifier } from './slack-failure-notifier'
import { SlackSigningSecretResolver } from './slack-secret-resolver'

const APP: AgentApplication = {
    id: 'app-1',
    team_id: 1,
    slug: 'demo',
    name: 'demo',
    description: '',
    live_revision_id: null,
    archived: false,
    encrypted_env: 'fernet-blob',
}

function makeSession(triggerMetadata: Record<string, unknown> | null): AgentSession {
    return {
        id: 'sess-1',
        application_id: APP.id,
        revision_id: 'rev-1',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: triggerMetadata,
        state: 'failed',
        conversation: [],
        pending_inputs: [],
        principal: null,
        retry_count: 0,
        usage_total: { input_tokens: 0, output_tokens: 0, cost_total: 0 },
        acl: [],
        pending_elevation_requests: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    } as unknown as AgentSession
}

function makeOkResponse(): Response {
    return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
    })
}

function tokenResolver(returns: string | null): SlackSigningSecretResolver {
    return { resolve: vi.fn(async () => returns) }
}

const SLACK_META = { type: 'slack', workspace_id: 'W1', channel: 'C1', ts: '111.222', thread_ts: '111.222' }

describe('SlackFailureNotifier', () => {
    it('posts a sanitized message to chat.postMessage on the originating thread', async () => {
        const fetch = vi.fn(async () => makeOkResponse())
        const http: HttpFetcher = { fetch: fetch as unknown as HttpFetcher['fetch'] }
        const n = new SlackFailureNotifier({ http, resolver: tokenResolver('xoxb-token') })

        await n.notify({
            session: makeSession(SLACK_META),
            application: APP,
            reason: 'docker run failed: Unable to find image',
            category: 'transient_infra',
        })

        expect(fetch).toHaveBeenCalledTimes(1)
        const [url, init] = fetch.mock.calls[0]!
        expect(url).toBe('https://slack.com/api/chat.postMessage')
        expect((init as RequestInit).method).toBe('POST')
        const headers = (init as RequestInit).headers as Record<string, string>
        expect(headers.Authorization).toBe('Bearer xoxb-token')
        const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>
        expect(body.channel).toBe('C1')
        expect(body.thread_ts).toBe('111.222')
        // Sanitized — raw infra detail must NOT leak.
        expect(body.text).toMatch(/try again/i)
        expect(JSON.stringify(body.text)).not.toMatch(/docker|image/i)
    })

    it('no-ops when trigger_metadata is not slack', async () => {
        const fetch = vi.fn()
        const http: HttpFetcher = { fetch: fetch as unknown as HttpFetcher['fetch'] }
        const n = new SlackFailureNotifier({ http, resolver: tokenResolver('xoxb-token') })

        await n.notify({
            session: makeSession({ type: 'webhook', url: 'https://example.com' }),
            application: APP,
            reason: 'x',
            category: 'unknown',
        })

        expect(fetch).not.toHaveBeenCalled()
    })

    it('no-ops when channel or thread_ts missing', async () => {
        const fetch = vi.fn()
        const http: HttpFetcher = { fetch: fetch as unknown as HttpFetcher['fetch'] }
        const n = new SlackFailureNotifier({ http, resolver: tokenResolver('xoxb-token') })

        await n.notify({
            session: makeSession({ type: 'slack', channel: 'C1' }),
            application: APP,
            reason: 'x',
            category: 'unknown',
        })

        expect(fetch).not.toHaveBeenCalled()
    })

    it('logs at warn and skips post when bot token is unresolved', async () => {
        const fetch = vi.fn()
        const http: HttpFetcher = { fetch: fetch as unknown as HttpFetcher['fetch'] }
        const logger = { warn: vi.fn(), info: vi.fn() }
        const n = new SlackFailureNotifier({ http, resolver: tokenResolver(null), logger })

        await n.notify({
            session: makeSession(SLACK_META),
            application: APP,
            reason: 'x',
            category: 'unknown',
        })

        expect(fetch).not.toHaveBeenCalled()
        expect(logger.warn).toHaveBeenCalledTimes(1)
        expect(logger.warn.mock.calls[0]![1]).toBe('slack_failure_notifier_no_bot_token')
    })

    it('swallows fetch throws and logs at warn — never rethrows', async () => {
        const fetch = vi.fn(async () => {
            throw new Error('network down')
        })
        const http: HttpFetcher = { fetch: fetch as unknown as HttpFetcher['fetch'] }
        const logger = { warn: vi.fn(), info: vi.fn() }
        const n = new SlackFailureNotifier({ http, resolver: tokenResolver('xoxb-token'), logger })

        await expect(
            n.notify({
                session: makeSession(SLACK_META),
                application: APP,
                reason: 'x',
                category: 'unknown',
            })
        ).resolves.toBeUndefined()
        expect(logger.warn).toHaveBeenCalledTimes(1)
        expect(logger.warn.mock.calls[0]![1]).toBe('slack_failure_notifier_post_threw')
    })

    it('logs at warn when slack returns ok=false (e.g. channel_not_found)', async () => {
        const fetch = vi.fn(
            async () =>
                new Response(JSON.stringify({ ok: false, error: 'channel_not_found' }), {
                    status: 200,
                    headers: { 'content-type': 'application/json' },
                })
        )
        const http: HttpFetcher = { fetch: fetch as unknown as HttpFetcher['fetch'] }
        const logger = { warn: vi.fn(), info: vi.fn() }
        const n = new SlackFailureNotifier({ http, resolver: tokenResolver('xoxb-token'), logger })

        await n.notify({
            session: makeSession(SLACK_META),
            application: APP,
            reason: 'x',
            category: 'unknown',
        })

        expect(logger.warn).toHaveBeenCalledTimes(1)
        expect(logger.warn.mock.calls[0]![1]).toBe('slack_failure_notifier_post_failed')
        expect(logger.warn.mock.calls[0]![0]).toMatchObject({ slack_error: 'channel_not_found' })
    })

    it('swallows resolver throws and skips post', async () => {
        const fetch = vi.fn()
        const http: HttpFetcher = { fetch: fetch as unknown as HttpFetcher['fetch'] }
        const logger = { warn: vi.fn(), info: vi.fn() }
        const throwingResolver: SlackSigningSecretResolver = {
            resolve: vi.fn(async () => {
                throw new Error('decrypt failed')
            }),
        }
        const n = new SlackFailureNotifier({ http, resolver: throwingResolver, logger })

        await expect(
            n.notify({
                session: makeSession(SLACK_META),
                application: APP,
                reason: 'x',
                category: 'unknown',
            })
        ).resolves.toBeUndefined()
        expect(fetch).not.toHaveBeenCalled()
        expect(logger.warn).toHaveBeenCalledTimes(1)
        expect(logger.warn.mock.calls[0]![1]).toBe('slack_failure_notifier_token_resolve_threw')
    })
})
