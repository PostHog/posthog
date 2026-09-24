import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { HeatmapAnalysisResultApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { HistoricalHeatmapDetail } from './HistoricalHeatmapDetail'
import { HistoricalHeatmaps } from './HistoricalHeatmaps'

const result: HeatmapAnalysisResultApi = {
    analysis: {
        id: '01900000-0000-7000-8000-000000000001',
        heatmap_id: '01900000-0000-7000-8000-000000000002',
        url: 'https://example.com/offers',
        date_from: '2026-01-01T00:00:00Z',
        date_to: '2026-01-15T00:00:00Z',
        viewport_width: 1440,
        status: 'completed',
        sampled_recordings: 120,
        excluded_recordings: 0,
        error: '',
        created_at: '2026-01-16T00:00:00Z',
        filters: { cohort_ids: [], events: [], filter_test_accounts: false },
    },
    analyzed_visits: 112,
    unavailable_recordings: 0,
    excluded_clicks: 14,
    variants: [0, 1, 2, 3, 4, 5].map((index) => ({
        id: String(index).repeat(24),
        session_id: `synthetic-session-${index}`,
        window_id: 1,
        timestamp: Date.UTC(2026, 0, index ? 10 : 3),
        width: 1440,
        height: 1600,
        recordings: index ? 32 : 78,
        visits: index ? 34 : 78,
        first_seen: Date.UTC(2026, 0, index * 2 + 1),
        last_seen: Date.UTC(2026, 0, index * 2 + 2),
        representative_replaced: false,
        clicks: [
            { x: 320, y: 330, count: 20 },
            { x: 1000, y: 1000, count: 8 },
        ],
        alternatives: [
            {
                id: `synthetic-session-${index}:1:${Date.UTC(2026, 0, index ? 10 : 3)}`,
                session_id: `synthetic-session-${index}`,
                timestamp: Date.UTC(2026, 0, index ? 10 : 3),
            },
        ],
    })),
}

const meta: Meta<typeof HistoricalHeatmaps> = {
    component: HistoricalHeatmaps,
    title: 'Web analytics/Historical heatmaps',
    args: { heatmapId: result.analysis.heatmap_id },
    parameters: {
        pageUrl: `/heatmap/example?historical_analysis=${result.analysis.id}`,
        featureFlags: [
            FEATURE_FLAGS.HEATMAPS_HISTORICAL_VARIANTS,
            FEATURE_FLAGS.HEATMAPS_COHORT_FILTER,
            FEATURE_FLAGS.HEATMAPS_EVENT_FILTER,
        ],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/heatmap_analyses/:id/': result,
                '/api/projects/:team_id/heatmap_analyses/:id/background/:variant_id/': ({ params }) =>
                    new Response(
                        `<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1600"><rect width="1440" height="1600" fill="#f6f4ed"/><rect x="48" y="48" width="1344" height="110" rx="8" fill="#234c3a"/><text x="80" y="120" font-size="48" font-family="sans-serif" fill="white">Example market</text><rect x="48" y="200" width="1344" height="380" rx="8" fill="${String(params.variant_id).startsWith('0') ? '#f6c85f' : '#b1d3e8'}"/><text x="80" y="300" font-size="56" font-family="sans-serif">${String(params.variant_id).startsWith('0') ? 'Fresh picks this week' : 'Pantry favorites'}</text><rect x="80" y="360" width="260" height="70" rx="8" fill="#234c3a"/><text x="105" y="408" font-size="28" font-family="sans-serif" fill="white">Browse offers</text><rect x="48" y="640" width="640" height="600" rx="8" fill="#e7b99e"/><rect x="752" y="640" width="640" height="600" rx="8" fill="#b6cbb2"/><text x="80" y="1350" font-size="40" font-family="sans-serif">More offers below the fold</text></svg>`,
                        { headers: { 'Content-Type': 'image/svg+xml' } }
                    ),
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof HistoricalHeatmaps>

export const Variants: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="max-w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const Empty: Story = { parameters: { pageUrl: '/heatmap/example' } }
export const ReadOnly: Story = { args: { disabledReason: 'Editor access is required to change this analysis.' } }

export const Detail: Story = {
    render: () => (
        <HistoricalHeatmapDetail
            variant={result.variants[0]}
            index={0}
            total={result.variants.length}
            timezone="UTC"
            backgroundUrl={`/api/projects/1/heatmap_analyses/${result.analysis.id}/background/${result.variants[0].id}/`}
            loading={false}
            onClose={() => {}}
            onNavigate={() => {}}
            onChooseMoment={() => {}}
        />
    ),
}

function withResult(
    overrides: Partial<HeatmapAnalysisResultApi>,
    analysis: Partial<HeatmapAnalysisResultApi['analysis']> = {}
): Story {
    return {
        decorators: [
            mswDecorator({
                get: {
                    '/api/projects/:team_id/heatmap_analyses/:id/': {
                        ...result,
                        ...overrides,
                        analysis: { ...result.analysis, ...analysis },
                    },
                },
            }),
        ],
    }
}

export const Partial: Story = withResult({ unavailable_recordings: 2 }, { status: 'partial', excluded_recordings: 8 })
export const NoMatches: Story = withResult({ variants: [], analyzed_visits: 0, excluded_clicks: 0 })
export const Processing: Story = {
    ...withResult({ variants: [] }, { status: 'processing' }),
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Unavailable: Story = withResult({ variants: [], analyzed_visits: 0 }, { status: 'unavailable' })
export const Failed: Story = withResult(
    { variants: [] },
    { status: 'failed', error: "Couldn't analyze these recordings. Try a shorter date range." }
)
