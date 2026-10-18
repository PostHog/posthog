import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import __dashboards from 'scenes/dashboard/__mocks__/dashboards.json'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import template from '../backend/suggested_dashboards/bank/otel-host.json'
import __results from './__mocks__/hostHealthResults.json'

// Renders the otel-host bank template as a dashboard, filled with results captured from a project
// seeded with three hosts: web-2 leaks memory to 93% and restarts, worker-1 saturates its CPU.
// The swap, page fault, context switch, runnable process, uptime and version results are generated to match that
// timeline, because the seed did not send those metrics. In them, web-2's leak is a canary version that rolls back.

const DASHBOARD_ID = 1
const REFRESHED_AT = '2026-10-15T00:47:12Z'

interface CapturedSeries {
    clause: string
    labels: Record<string, string>
    metricName: string | null
    unit: string | null
    values: (number | null)[]
}

interface CapturedResult {
    start: string
    stepSeconds: number
    series: CapturedSeries[]
}

const results = __results as Record<string, CapturedResult>

const toResponse = ({ start, stepSeconds, series }: CapturedResult): Record<string, unknown>[] =>
    series.map(({ values, ...rest }) => ({
        ...rest,
        points: values.map((value, index) => ({
            time: new Date(Date.parse(start) + index * stepSeconds * 1000).toISOString(),
            value,
        })),
    }))

const panelKeyByQuery = new Map<string, string>()
const queryKey = (query: Record<string, unknown>): string =>
    JSON.stringify([query.clauses, query.formula ?? null, query.interval ?? null])

const tiles = template.panels.map((panel, index) => {
    const tile = {
        id: index + 1,
        layouts: { sm: panel.layout },
        color: null,
        is_cached: true,
        last_refresh: REFRESHED_AT,
    }
    if (!('query' in panel) || !panel.query) {
        return { ...tile, insight: null, text: { body: panel.text } }
    }
    panelKeyByQuery.set(queryKey(panel.query), panel.key)
    return {
        ...tile,
        text: null,
        insight: {
            id: 100 + index,
            short_id: `otelh${String(index).padStart(3, '0')}`,
            name: panel.title,
            derived_name: null,
            description: 'description' in panel ? panel.description : '',
            query: { ...panel.query, dateRange: { date_from: '-6h' } },
            result: toResponse(results[panel.key]),
            last_refresh: REFRESHED_AT,
            is_cached: true,
            timezone: 'UTC',
            dashboards: [DASHBOARD_ID],
            deleted: false,
            saved: true,
            favorited: false,
            tags: [],
            created_at: '2026-10-14T18:00:00Z',
            created_by: null,
        },
    }
})

const dashboard = {
    id: DASHBOARD_ID,
    name: template.name,
    description: template.description,
    pinned: false,
    created_at: '2026-10-14T18:00:00Z',
    created_by: null,
    creation_mode: 'template',
    deleted: false,
    filters: {},
    is_shared: false,
    tags: [],
    tiles,
}

const insights = tiles.flatMap((tile) => (tile.insight ? [tile.insight] : []))

const queryHandler = async ({ request }: { request: Request }): Promise<unknown> => {
    const { query } = (await request.json()) as { query: Record<string, unknown> }
    const key = panelKeyByQuery.get(queryKey(query))
    return key ? [200, { results: toResponse(results[key]) }] : [200, { results: [] }]
}

const meta: Meta = {
    component: App,
    title: 'Products/Metrics/APM dashboard',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-15T00:50:00Z',
        pageUrl: urls.dashboard(DASHBOARD_ID),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': __dashboards as any,
                [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: dashboard,
                '/api/environments/:team_id/insights/:id/': ({ params }) => {
                    const insight = insights.find((candidate) => String(candidate.id) === params.id)
                    return insight ? [200, insight] : [404, { detail: 'Insight not found' }]
                },
                '/api/environments/:team_id/session_recordings/': EMPTY_PAGINATED_RESPONSE,
                '/api/environments/:team_id/insights/my_last_viewed/': [],
                '/api/environments/:team_id/warehouse/variables/': [],
                '/api/projects/:team_id/events_retention/': [200, { retention_months: null, retained_from: null }],
            },
            post: {
                '/api/environments/:team_id/query/': queryHandler,
                '/api/environments/:team_id/query/:query_kind/': queryHandler,
                '/api/environments/:team_id/insights/cancel/': [201],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const APM: Story = {}
