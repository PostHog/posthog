import { vi } from 'vitest'

import type { HttpFetcher } from '@posthog/agent-shared'

import { makeCtx } from '../test-helpers'
import { httpRequestV1 } from './http-request.v1'

/** Fake fetch response builder. */
function fakeResponse(opts: {
    status?: number
    text?: string
    contentType?: string
    headers?: Record<string, string>
}): Response {
    const status = opts.status ?? 200
    const text = opts.text ?? ''
    const headerEntries: Array<[string, string]> = Object.entries(opts.headers ?? {})
    if (opts.contentType !== undefined) {
        headerEntries.push(['content-type', opts.contentType])
    }
    return {
        ok: status >= 200 && status < 300,
        status,
        text: async () => text,
        headers: {
            get: (k: string) => headerEntries.find(([h]) => h.toLowerCase() === k.toLowerCase())?.[1] ?? null,
            entries: () => headerEntries[Symbol.iterator](),
        },
    } as unknown as Response
}

/**
 * Build an HttpFetcher whose `fetch` records the call args and returns the
 * supplied response. Replaces the old `global.fetch = vi.fn(...)` pattern —
 * tests inject this via `makeCtx({ http })` so the tool reaches it through
 * `ctx.http.fetch` (matching the prod path).
 */
function captureFetch(response: Response): {
    http: HttpFetcher
    lastCall: { url?: string; init?: RequestInit }
} {
    const captured: { url?: string; init?: RequestInit } = {}
    const http: HttpFetcher = {
        fetch: async (input, init) => {
            captured.url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : ''
            captured.init = init
            return response
        },
    }
    return { http, lastCall: captured }
}

describe('@posthog/http-request', () => {
    describe('basic dispatch', () => {
        it('defaults to GET when method is omitted', async () => {
            const { http, lastCall } = captureFetch(
                fakeResponse({ status: 200, text: 'ok', contentType: 'text/plain' })
            )
            const out = await httpRequestV1.run({ url: 'https://example.com/ping' }, makeCtx({ http }))
            expect(lastCall.init?.method).toBe('GET')
            expect(out.status).toBe(200)
            expect(out.body).toBe('ok')
        })

        it.each(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const)('forwards method %s to fetch', async (method) => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 204 }))
            await httpRequestV1.run({ url: 'https://example.com/x', method }, makeCtx({ http }))
            expect(lastCall.init?.method).toBe(method)
        })

        it('returns the status, body, content_type, and a small allowlisted header subset', async () => {
            const { http } = captureFetch(
                fakeResponse({
                    status: 201,
                    text: '{"ok":true}',
                    contentType: 'application/json',
                    headers: { 'content-length': '11', 'x-custom-leak': 'should-not-surface' },
                })
            )
            const out = await httpRequestV1.run({ url: 'https://example.com/api' }, makeCtx({ http }))
            expect(out.status).toBe(201)
            expect(out.body).toBe('{"ok":true}')
            expect(out.content_type).toBe('application/json')
            expect(out.headers).toEqual({ 'content-length': '11', 'content-type': 'application/json' })
            expect(out.headers).not.toHaveProperty('x-custom-leak')
        })
    })

    describe('body serialization', () => {
        it('passes a string body through verbatim and does NOT set Content-Type for the caller', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run(
                {
                    url: 'https://example.com/x',
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'channel=C123&text=hi',
                },
                makeCtx({ http })
            )
            expect(lastCall.init?.body).toBe('channel=C123&text=hi')
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers['Content-Type']).toBe('application/x-www-form-urlencoded')
        })

        it('JSON-encodes an object body and stamps Content-Type when the caller did not set it', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run(
                {
                    url: 'https://slack.com/api/chat.postMessage',
                    method: 'POST',
                    body: { channel: 'C123', text: 'hello' },
                },
                makeCtx({ http })
            )
            expect(lastCall.init?.body).toBe('{"channel":"C123","text":"hello"}')
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers['Content-Type']).toBe('application/json; charset=utf-8')
        })

        it('does NOT override a caller-supplied Content-Type on an object body', async () => {
            // Author wants to send JSON under a vendor-specific content-type;
            // the tool must not silently rewrite it. Case-insensitive match.
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run(
                {
                    url: 'https://example.com/x',
                    method: 'POST',
                    headers: { 'content-type': 'application/vnd.api+json' },
                    body: { foo: 'bar' },
                },
                makeCtx({ http })
            )
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers['content-type']).toBe('application/vnd.api+json')
            expect(headers).not.toHaveProperty('Content-Type')
        })

        it('omits the body entirely for GET requests when none was passed', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run({ url: 'https://example.com/x' }, makeCtx({ http }))
            expect(lastCall.init?.body).toBeUndefined()
        })
    })

    describe('secret substitution', () => {
        it('substitutes ${NAME} placeholders in url, headers, and string body', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            const ctx = makeCtx({
                http,
                secret: (name) => ({ TENANT: 'acme', SLACK_BOT_TOKEN: 'xoxb-real-token' })[name],
            })
            await httpRequestV1.run(
                {
                    url: 'https://${TENANT}.example.com/api',
                    method: 'POST',
                    headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                    body: 'tenant=${TENANT}',
                },
                ctx
            )
            expect(lastCall.url).toBe('https://acme.example.com/api')
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers.Authorization).toBe('Bearer xoxb-real-token')
            expect(lastCall.init?.body).toBe('tenant=acme')
        })

        it('substitutes ${NAME} inside JSON-encoded object bodies', async () => {
            // Slack's legacy token-in-body form. Author shouldn't have to
            // worry about JSON-encoding the placeholder.
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            const ctx = makeCtx({
                http,
                secret: (name) => (name === 'SLACK_BOT_TOKEN' ? 'xoxb-abc' : undefined),
            })
            await httpRequestV1.run(
                {
                    url: 'https://slack.com/api/auth.test',
                    method: 'POST',
                    body: { token: '${SLACK_BOT_TOKEN}' },
                },
                ctx
            )
            expect(lastCall.init?.body).toBe('{"token":"xoxb-abc"}')
        })

        it('throws secret_not_resolved when a referenced secret is missing', async () => {
            // Fail loudly rather than send a literal `${NAME}` upstream — the
            // remote would 401 with a confusing error that's hard to debug.
            const { http } = captureFetch(fakeResponse({ status: 200 }))
            await expect(
                httpRequestV1.run(
                    {
                        url: 'https://example.com/x',
                        method: 'POST',
                        headers: { Authorization: 'Bearer ${MISSING}' },
                    },
                    makeCtx({ http })
                )
            ).rejects.toThrow(/secret_not_resolved: MISSING/)
        })

        it('only substitutes UPPERCASE_SNAKE placeholders — leaves shell-style ${1} alone', async () => {
            // Defensive: the regex requires names that start with [A-Z] and use
            // only [A-Z0-9_]. Things like `${1}` or `${something}` are pass-through
            // so authors who put literal `${foo}` in a JSON path or shell snippet
            // don't see their data mangled.
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run(
                { url: 'https://example.com/x', body: 'shell=${1} mixed=${foo}' },
                makeCtx({ http })
            )
            expect(lastCall.init?.body).toBe('shell=${1} mixed=${foo}')
        })
    })

    describe('limits', () => {
        it('truncates response body to max_response_bytes', async () => {
            const big = 'x'.repeat(10_000)
            const { http } = captureFetch(fakeResponse({ status: 200, text: big }))
            const out = await httpRequestV1.run(
                { url: 'https://example.com/x', max_response_bytes: 100 },
                makeCtx({ http })
            )
            expect(out.body.length).toBe(100)
            expect(out.truncated).toBe(true)
        })

        it('marks truncated=false when the body fits under the cap', async () => {
            const { http } = captureFetch(fakeResponse({ status: 200, text: 'small' }))
            const out = await httpRequestV1.run({ url: 'https://example.com/x' }, makeCtx({ http }))
            expect(out.truncated).toBe(false)
        })

        it('rejects invalid URLs with a clear error before calling fetch', async () => {
            // Different error class than http_request_failed so the model can
            // tell "I sent a malformed URL" apart from "the network blew up."
            const http: HttpFetcher = {
                fetch: vi.fn(async () => {
                    throw new Error('should not be called')
                }),
            }
            await expect(httpRequestV1.run({ url: 'not a url' }, makeCtx({ http }))).rejects.toThrow(/invalid_url/)
        })

        it('surfaces fetch failures as http_request_failed', async () => {
            const http: HttpFetcher = {
                fetch: vi.fn(async () => {
                    throw new Error('ECONNREFUSED')
                }),
            }
            await expect(httpRequestV1.run({ url: 'https://example.com/x' }, makeCtx({ http }))).rejects.toThrow(
                /http_request_failed: ECONNREFUSED/
            )
        })

        it('surfaces AbortError as http_request_timeout', async () => {
            // The runtime aborts the fetch via AbortController on timeout; the
            // tool translates the resulting AbortError into a friendlier
            // message that includes the timeout value.
            const http: HttpFetcher = {
                fetch: vi.fn(async () => {
                    const e: Error & { name?: string } = new Error('aborted')
                    e.name = 'AbortError'
                    throw e
                }),
            }
            await expect(
                httpRequestV1.run({ url: 'https://example.com/x', timeout_ms: 50 }, makeCtx({ http }))
            ).rejects.toThrow(/http_request_timeout: 50ms/)
        })
    })
})
