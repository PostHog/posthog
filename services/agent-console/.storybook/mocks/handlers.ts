/**
 * MSW request handlers — mirror the read surface of PostHog Django.
 *
 * Path nesting + response shapes follow `products/agent_stack/backend/
 * api.py`. When the real backend lands, deleting `.storybook/mocks/`
 * and pointing the Next.js rewrites at the real hosts is the swap.
 *
 * The console is read-mostly — writes go through the agent runner
 * (Django MCP / direct REST). Nothing in this file mocks writes.
 */

import { http, HttpResponse } from 'msw'

import {
    getAgentBySlugStore,
    getAgentStatsStore,
    getBundleRawStore,
    getFleetStatsStore,
    getSessionStore,
    listAgentsStore,
    listLiveSessionsStore,
    listLogsForSessionStore,
    listRevisionsStore,
    listSessionsForAgentStore,
} from './store'

const PROJECT_PREFIX = '/api/projects/:projectId'

/** Project id the AppShell story's session resolves to. The store
 * doesn't actually scope by team — it serves the same fixture pool
 * regardless — so the choice is arbitrary, but the same number has to
 * appear here and in everything the apiClient builds. */
const STORYBOOK_TEAM_ID = 1

export const handlers = [
    /* Session — `SessionProvider` hits this on mount. Returns a stable
     * fake identity so the SessionGate falls through and the shell
     * renders its child content. */
    http.get('/api/auth/me', () => {
        return HttpResponse.json({
            authenticated: true,
            teamId: STORYBOOK_TEAM_ID,
            posthogBaseUrl: 'https://app.posthog.com',
            oidc: { sub: 'storybook-fake-sub' },
            profile: {
                email: 'storybook@posthog.com',
                first_name: 'Story',
                last_name: 'Book',
                team: { id: STORYBOOK_TEAM_ID, name: 'Storybook project' },
            },
        })
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/`, ({ request }) => {
        const url = new URL(request.url)
        const includeArchived = url.searchParams.get('include_archived') === 'true'
        return HttpResponse.json({ results: listAgentsStore({ includeArchived }) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/`, ({ params }) => {
        const agent = getAgentBySlugStore(params.slug as string)
        if (!agent) {
            return HttpResponse.json({ error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json(agent)
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/revisions/`, ({ params }) => {
        const slug = params.slug as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json({ results: listRevisionsStore(slug) })
    }),

    /**
     * Bulk-pull a revision's bundle. Django shape: `{ files: { path:
     * content }, sha256, ... }`. The apiClient transforms to
     * `BundleFile[]` on the client side.
     */
    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/revisions/:revisionId/bundle/`, ({ params }) => {
        const slug = params.slug as string
        const revisionId = params.revisionId as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json(getBundleRawStore(slug, revisionId))
    }),

    /* Sessions proxied through the application — no standalone
     * /agent_sessions route in Django.
     */
    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/sessions/`, ({ params }) => {
        const slug = params.slug as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json({ results: listSessionsForAgentStore(slug) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/sessions/:sessionId/`, ({ params }) => {
        const slug = params.slug as string
        const sessionId = params.sessionId as string
        if (!getAgentBySlugStore(slug)) {
            return HttpResponse.json({ error: 'not_found' }, { status: 404 })
        }
        const session = getSessionStore(sessionId)
        if (!session || session.application.slug !== slug) {
            return HttpResponse.json({ error: 'session_not_found' }, { status: 404 })
        }
        return HttpResponse.json(session)
    }),

    /* Console-only endpoints (mocked; Phase C builds them on Django). */
    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/stats/`, ({ params }) => {
        const stats = getAgentStatsStore(params.slug as string)
        if (!stats) {
            return HttpResponse.json({ error: 'not_found' }, { status: 404 })
        }
        return HttpResponse.json(stats)
    }),

    http.get(`${PROJECT_PREFIX}/agent_applications/:slug/sessions/:sessionId/logs/`, ({ params }) => {
        return HttpResponse.json({ results: listLogsForSessionStore(params.sessionId as string) })
    }),

    http.get(`${PROJECT_PREFIX}/agent_fleet/stats/`, () => {
        return HttpResponse.json(getFleetStatsStore())
    }),

    http.get(`${PROJECT_PREFIX}/agent_fleet/live_sessions/`, () => {
        return HttpResponse.json({ results: listLiveSessionsStore() })
    }),
]
