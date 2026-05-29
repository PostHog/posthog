/**
 * MSW request handlers — the v0 REST contract the console code
 * actually targets.
 *
 * All paths use `/api/projects/:projectId/...` to match the shape the
 * real PostHog / agent-ingress endpoints will use. The handlers are
 * thin: parse path/query, call into `store.ts`, serialize. When the
 * real backend lands, deleting `.storybook/mocks/` and pointing the
 * API base at it is the swap.
 *
 * Conventions:
 *   - Reads return `{ results: T[] }` for lists, `T` directly for detail.
 *   - Writes return `{ ok: true, mutationId }` after recording.
 *   - Errors return `{ ok: false, error }` with appropriate status.
 *
 * The `/agent_events/stream/` endpoint is an SSE stream (text/event-stream)
 * that emits a `mutation` event each time the store records one.
 */

import { http, HttpResponse } from 'msw'

import {
    countLiveSessionsForAgentStore,
    getAgentBySlugStore,
    getAgentStatsStore,
    getBundleStore,
    getFleetStatsStore,
    getSessionStore,
    listAgentsStore,
    listLiveSessionsStore,
    listLogsForSessionStore,
    listRevisionsStore,
    listSessionsForAgentStore,
    subscribeMutationEvents,
    writeBundleFile,
    writeRevisionSpecPatch,
    type BundleFileWrite,
    type MutationEvent,
    type RevisionSpecPatchWrite,
} from './store'

/**
 * Two path prefixes — mirror what Next.js rewrites to in prod:
 *   `/api/projects/:projectId/...`  → PostHog Django REST (CRUD)
 *   `/api/agents/v1/...`            → agent-ingress (runtime + streaming)
 */
const PROJECT_PREFIX = '/api/projects/:projectId'
const INGRESS_PREFIX = '/api/agents/v1'

/* ── Read handlers ───────────────────────────────────────────────── */

const readHandlers = [
    http.get(`${PROJECT_PREFIX}/agent_applications/`, ({ request }) => {
        const url = new URL(request.url)
        const includeArchived = url.searchParams.get('include_archived') === 'true'
        return HttpResponse.json({ results: listAgentsStore({ includeArchived }) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/`, ({ params }) => {
        const agent = getAgentBySlugStore(params.slug as string)
        if (!agent) {
            return HttpResponse.json({ ok: false, error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json(agent)
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/revisions/`, ({ params }) => {
        const slug = params.slug as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ ok: false, error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json({ results: listRevisionsStore(slug) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/bundle/`, ({ params }) => {
        const slug = params.slug as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ ok: false, error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json({ results: getBundleStore(slug) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/stats/`, ({ params }) => {
        const slug = params.slug as string
        const stats = getAgentStatsStore(slug)
        if (!stats) {
            return HttpResponse.json({ ok: false, error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json(stats)
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/sessions/`, ({ params }) => {
        const slug = params.slug as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ ok: false, error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json({ results: listSessionsForAgentStore(slug) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/live_session_count/`, ({ params }) => {
        const slug = params.slug as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ ok: false, error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json({ count: countLiveSessionsForAgentStore(slug) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_sessions/:sessionId/`, ({ params }) => {
        const session = getSessionStore(params.sessionId as string)
        if (!session) {
            return HttpResponse.json({ ok: false, error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json(session)
    }),

    http.get(`${PROJECT_PREFIX}/agent_sessions/:sessionId/logs/`, ({ params }) => {
        return HttpResponse.json({ results: listLogsForSessionStore(params.sessionId as string) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_fleet/stats/`, () => {
        return HttpResponse.json(getFleetStatsStore())
    }),

    http.get(`${PROJECT_PREFIX}/agent_fleet/live_sessions/`, () => {
        return HttpResponse.json({ results: listLiveSessionsStore() })
    }),
]

/* ── Write handlers ──────────────────────────────────────────────── */

const writeHandlers = [
    /**
     * PUT a bundle file. Body: `{ newContent, mutationId }`. The
     * mutationId is supplied by the caller (the agent runner) so the
     * resulting SSE event correlates with the call's focus payload.
     */
    http.put(`${PROJECT_PREFIX}/agent_applications/:slug/bundle/files/`, async ({ params, request }) => {
        const url = new URL(request.url)
        const path = url.searchParams.get('path')
        if (!path) {
            return HttpResponse.json({ ok: false, error: 'missing_path' }, { status: 400 })
        }
        const slug = params.slug as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ ok: false, error: 'agent_not_found' }, { status: 404 })
        }
        const body = (await request.json()) as BundleFileWrite
        writeBundleFile(slug, path, body)
        return HttpResponse.json({ ok: true, mutationId: body.mutationId })
    }),

    /**
     * PATCH a revision spec. Body: `{ applicationSlug, patch, mutationId }`.
     * v0 demo patches the spec in place; v0.1 will create a new
     * revision instead, but the request shape stays the same.
     */
    http.patch(`${PROJECT_PREFIX}/agent_revisions/:revisionId/spec/`, async ({ params, request }) => {
        const body = (await request.json()) as RevisionSpecPatchWrite & { applicationSlug: string }
        if (!body.applicationSlug) {
            return HttpResponse.json({ ok: false, error: 'missing_applicationSlug' }, { status: 400 })
        }
        writeRevisionSpecPatch(body.applicationSlug, params.revisionId as string, body)
        return HttpResponse.json({ ok: true, mutationId: body.mutationId })
    }),
]

/* ── SSE stream ──────────────────────────────────────────────────── */

const streamHandler = http.get(`${INGRESS_PREFIX}/events/stream`, () => {
    const encoder = new TextEncoder()
    let unsubscribe: (() => void) | null = null
    let keepalive: ReturnType<typeof setInterval> | null = null
    const stream = new ReadableStream({
        start(controller) {
            unsubscribe = subscribeMutationEvents((event: MutationEvent) => {
                const payload = JSON.stringify(event)
                try {
                    controller.enqueue(encoder.encode(`event: mutation\ndata: ${payload}\n\n`))
                } catch {
                    // Stream already closed — listener will be cleaned up via cancel().
                }
            })
            // Keep-alive so the connection survives proxies that idle-time
            // text/event-stream after ~30s.
            keepalive = setInterval(() => {
                try {
                    controller.enqueue(encoder.encode(`: keepalive\n\n`))
                } catch {
                    if (keepalive) {
                        clearInterval(keepalive)
                        keepalive = null
                    }
                }
            }, 25_000)
        },
        cancel(): void {
            unsubscribe?.()
            if (keepalive) {
                clearInterval(keepalive)
            }
        },
    })
    return new HttpResponse(stream, {
        headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache, no-store',
            Connection: 'keep-alive',
        },
    })
})

export const handlers = [...readHandlers, ...writeHandlers, streamHandler]
