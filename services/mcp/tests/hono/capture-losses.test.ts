import { gunzipSync } from 'node:zlib'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PostHogMCP } from '@posthog/mcp-analytics'

import { recordCaptureLosses } from '@/hono/capture-losses'
import { posthogCaptureEventsLostTotal } from '@/hono/metrics'

const ANALYTICS_ENDPOINT = '/i/v1/analytics/events'
const DROP_DETAILS: Record<string, string | undefined> = {
    'too long event': 'event_name_too_long',
    'over quota event': 'events_over_quota',
    'unexplained event': undefined,
    'garbled event': '<html>502 Bad Gateway</html>',
}

describe('recordCaptureLosses', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
        posthogCaptureEventsLostTotal.reset()
    })

    it('counts the events capture v1 did not accept, by endpoint and reason', async () => {
        const requests: { url: string; authorization?: string; events: string[] }[] = []
        vi.stubGlobal(
            'fetch',
            vi.fn(async (url: string, options: RequestInit) => {
                const body =
                    typeof options.body === 'string' ? options.body : gunzipSync(options.body as Uint8Array).toString()
                const batch: { event: string; uuid: string }[] = JSON.parse(body).batch
                requests.push({
                    url,
                    authorization: (options.headers as Record<string, string>).Authorization,
                    events: batch.map((event) => event.event),
                })
                if (batch.some((event) => event.event === 'rejected request event')) {
                    return new Response('{"error":"billing_limit_exceeded"}', { status: 402 })
                }
                const results = Object.fromEntries(
                    batch.map((event) => [
                        event.uuid,
                        event.event in DROP_DETAILS
                            ? { result: 'drop', details: DROP_DETAILS[event.event] }
                            : { result: 'ok' },
                    ])
                )
                return new Response(JSON.stringify({ results }), { status: 200 })
            })
        )
        const client = new PostHogMCP('phc_test', { host: 'https://example.com', flushAt: 1, flushInterval: 0 })
        recordCaptureLosses(client)

        const events = ['delivered event', ...Object.keys(DROP_DETAILS), 'too long event', 'rejected request event']
        for (const event of events) {
            client.capture({ distinctId: 'user-123', event })
            await client.flush()
        }
        await client.shutdown()

        const lost = (await posthogCaptureEventsLostTotal.get()).values
        expect(Object.fromEntries(lost.map((v) => [`${v.labels.endpoint} ${v.labels.reason}`, v.value]))).toEqual({
            [`${ANALYTICS_ENDPOINT} event_name_too_long`]: 2,
            [`${ANALYTICS_ENDPOINT} events_over_quota`]: 1,
            [`${ANALYTICS_ENDPOINT} other`]: 2,
            [`${ANALYTICS_ENDPOINT} undelivered`]: 1,
        })
        expect(requests).toEqual(
            events.map((event) => ({
                url: `https://example.com${ANALYTICS_ENDPOINT}`,
                authorization: 'Bearer phc_test',
                events: [event],
            }))
        )
    })
})
