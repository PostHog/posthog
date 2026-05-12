import { createParser } from 'eventsource-parser'
import type { z } from 'zod'

import { LivestreamReadSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = LivestreamReadSchema

type Params = z.infer<typeof schema>

const DEFAULT_WAIT_SECONDS = 10
const MAX_WAIT_SECONDS = 30
const DEFAULT_LIMIT = 50
const MAX_LIMIT = 200

export type LivestreamEvent = {
    uuid?: string
    event: string
    distinct_id?: string
    timestamp?: string | number | null
    properties?: Record<string, unknown>
}

type LivestreamReadResult = {
    livestream_host: string
    waited_seconds: number
    event_count: number
    events: LivestreamEvent[]
    notice?: string
}

const REGION_HOST_MAP: Record<string, string> = {
    'https://us.posthog.com': 'https://live.us.posthog.com',
    'https://eu.posthog.com': 'https://live.eu.posthog.com',
    'https://app.dev.posthog.dev': 'https://live.dev.posthog.dev',
}

export function getLivestreamHost(apiBaseUrl: string): string {
    const mapped = REGION_HOST_MAP[apiBaseUrl]
    if (mapped) {
        return mapped
    }
    if (apiBaseUrl.startsWith('http://localhost') || apiBaseUrl.startsWith('http://127.0.0.1')) {
        return 'http://localhost:8666'
    }
    throw new Error(
        `Livestream is not reachable from base URL "${apiBaseUrl}". The livestream tool currently supports PostHog Cloud (US/EU) and local development.`
    )
}

function buildLivestreamUrl(host: string, params: Params): string {
    const url = new URL(`${host}/events`)
    if (params.event_types && params.event_types.length > 0) {
        url.searchParams.set('eventType', params.event_types.join(','))
    }
    if (params.distinct_id) {
        url.searchParams.set('distinctId', params.distinct_id)
    }
    if (params.properties) {
        for (const [key, value] of Object.entries(params.properties)) {
            url.searchParams.append('property', `${key}=${value}`)
        }
    }
    return url.toString()
}

export async function collectLivestreamEvents(opts: {
    url: string
    token: string
    limit: number
    waitMs: number
}): Promise<{ events: LivestreamEvent[]; waitedMs: number }> {
    const controller = new AbortController()
    const collected: LivestreamEvent[] = []
    const startedAt = Date.now()
    const timeoutId = setTimeout(() => controller.abort(), opts.waitMs)

    let response: Response
    try {
        response = await fetch(opts.url, {
            method: 'GET',
            headers: {
                Authorization: `Bearer ${opts.token}`,
                Accept: 'text/event-stream',
            },
            signal: controller.signal,
        })
    } catch (err) {
        clearTimeout(timeoutId)
        if ((err as Error).name === 'AbortError') {
            return { events: collected, waitedMs: Date.now() - startedAt }
        }
        throw err
    }

    if (!response.ok) {
        clearTimeout(timeoutId)
        const errorText = await response.text().catch(() => '')
        throw new Error(
            `Livestream request failed: ${response.status} ${response.statusText}${errorText ? ` — ${errorText}` : ''}`
        )
    }

    if (!response.body) {
        clearTimeout(timeoutId)
        throw new Error('Livestream response has no body')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()

    const parser = createParser({
        onEvent: ({ data }) => {
            try {
                const parsed = JSON.parse(data) as LivestreamEvent
                collected.push(parsed)
                if (collected.length >= opts.limit) {
                    controller.abort()
                }
            } catch {
                // Skip non-JSON SSE keepalive/comment frames.
            }
        },
    })

    try {
        while (true) {
            const { done, value } = await reader.read()
            if (done) {
                break
            }
            parser.feed(decoder.decode(value, { stream: true }))
            if (collected.length >= opts.limit) {
                break
            }
        }
    } catch (err) {
        if ((err as Error).name !== 'AbortError') {
            throw err
        }
    } finally {
        clearTimeout(timeoutId)
        await reader.cancel().catch(() => undefined)
        reader.releaseLock()
    }

    return { events: collected, waitedMs: Date.now() - startedAt }
}

export const livestreamReadHandler: ToolBase<typeof schema, LivestreamReadResult>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const projectResult = await context.api.projects().get({ projectId })
    if (!projectResult.success) {
        throw new Error(`Failed to load project: ${projectResult.error.message}`)
    }
    const liveEventsToken = projectResult.data.live_events_token
    if (!liveEventsToken) {
        throw new Error(
            'No live_events_token available for this project. The current API key may not have permission to mint a livestream token.'
        )
    }

    const host = getLivestreamHost(context.api.baseUrl)
    const url = buildLivestreamUrl(host, params)

    const limit = Math.min(params.limit ?? DEFAULT_LIMIT, MAX_LIMIT)
    const waitSeconds = Math.min(params.wait_seconds ?? DEFAULT_WAIT_SECONDS, MAX_WAIT_SECONDS)

    const { events, waitedMs } = await collectLivestreamEvents({
        url,
        token: liveEventsToken,
        limit,
        waitMs: waitSeconds * 1000,
    })

    const result: LivestreamReadResult = {
        livestream_host: host,
        waited_seconds: Math.round(waitedMs / 100) / 10,
        event_count: events.length,
        events,
    }
    if (events.length === 0) {
        result.notice =
            'No events were captured in the listening window. The livestream only returns events ingested after the connection is opened — verify the event is being fired right now (e.g. trigger the action in the app), or extend wait_seconds.'
    }
    return result
}

const tool = (): ToolBase<typeof schema, LivestreamReadResult> => ({
    name: 'livestream-read',
    schema,
    handler: livestreamReadHandler,
})

export default tool
