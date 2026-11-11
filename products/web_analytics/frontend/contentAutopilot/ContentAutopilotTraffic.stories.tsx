import type { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { contentAutopilotAiTrafficLogic } from './contentAutopilotAiTrafficLogic'
import { ContentAutopilotTraffic } from './ContentAutopilotTraffic'

const DAYS = Array.from({ length: 30 }, (_, index) => `2026-09-${String(index + 1).padStart(2, '0')}`)

const series = (label: string, base: number): Record<string, unknown> => {
    const data = DAYS.map((_, index) => Math.round(base + base * 0.4 * Math.sin(index / 3) + index * (base / 30)))
    return {
        label,
        breakdown_value: label,
        data,
        days: DAYS,
        labels: DAYS,
        count: data.reduce((sum, value) => sum + value, 0),
        action: { id: '$pageview', type: 'events', order: 0, name: '$pageview', math: 'unique_session' },
    }
}

const overviewItem = (key: string, value: number, kind: string = 'unit'): Record<string, unknown> => ({
    key,
    value,
    kind,
})

const ENTRY_PAGES = [
    ['/docs/getting-started', 412, 198],
    ['/pricing', 288, 131],
    ['/', 241, 117],
    ['/blog/self-hosted-analytics', 156, 74],
    ['/docs/api/query', 98, 51],
]

const CITED_PAGES = [
    ['/docs/getting-started', 18],
    ['/blog/self-hosted-analytics/', 11],
    ['/docs/compare/feature-flags', 9],
    ['/docs/data/retention', 6],
    ['/pricing', 4],
]

const queryHandlers = ({ hasAiTraffic }: { hasAiTraffic: boolean }): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        post: {
            '/api/environments/:team_id/query/:kind': async ({ request }) => {
                const query = ((await request.json()) as any).query
                const source = query.source ?? query
                switch (source.kind) {
                    case 'WebOverviewQuery': {
                        const aiOnly = (source.properties ?? []).length > 0
                        if (source.conversionGoal) {
                            return [
                                200,
                                {
                                    results: [
                                        overviewItem('visitors', aiOnly ? 1120 : 48200),
                                        overviewItem('unique conversions', aiOnly ? 58 : 1350),
                                        overviewItem('conversion rate', aiOnly ? 5.2 : 2.8, 'percentage'),
                                    ],
                                },
                            ]
                        }
                        const sessions = aiOnly ? (hasAiTraffic ? 1460 : 0) : 61500
                        const visitors = aiOnly ? (hasAiTraffic ? 1120 : 0) : 48200
                        return [
                            200,
                            {
                                results: [overviewItem('visitors', visitors), overviewItem('sessions', sessions)],
                            },
                        ]
                    }
                    case 'TrendsQuery':
                        return [
                            200,
                            {
                                results: hasAiTraffic
                                    ? [
                                          series('answers.example.com', 24),
                                          series('chat.example.org', 12),
                                          series('search.example.net', 6),
                                      ]
                                    : [],
                            },
                        ]
                    case 'WebStatsTableQuery':
                        return [
                            200,
                            {
                                columns: [
                                    'context.columns.breakdown_value',
                                    'context.columns.visitors',
                                    'context.columns.views',
                                    'context.columns.total_conversions',
                                    'context.columns.conversion_rate',
                                ],
                                results: hasAiTraffic
                                    ? ENTRY_PAGES.map(([page, visitors, conversions]) => [
                                          page,
                                          [visitors, null],
                                          [Number(visitors) * 2, null],
                                          [Math.round(Number(conversions) / 10), null],
                                          [Number(conversions) / Number(visitors) / 10, null],
                                      ])
                                    : [],
                            },
                        ]
                    case 'HogQLQuery':
                        if (source.query.includes('aeo_citation_checks')) {
                            return [200, { columns: ['page', 'answers'], results: CITED_PAGES }]
                        }
                        return [
                            200,
                            {
                                columns: ['page', 'sessions'],
                                results: hasAiTraffic ? ENTRY_PAGES.map(([page, , sessions]) => [page, sessions]) : [],
                            },
                        ]
                }
                return [200, { results: [] }]
            },
        },
    })

const meta: Meta<typeof ContentAutopilotTraffic> = {
    title: 'Products/Web Analytics/Content autopilot/Traffic',
    component: ContentAutopilotTraffic,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT, FEATURE_FLAGS.AEO_CITATION_TRACKING],
        mockDate: '2026-09-30',
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

const TrafficWithGoal = (): JSX.Element => {
    const { setConversionGoal } = useActions(contentAutopilotAiTrafficLogic)
    useEffect(() => {
        setConversionGoal({ customEventName: 'signed_up' })
    }, [setConversionGoal])
    return (
        <div className="p-6">
            <ContentAutopilotTraffic />
        </div>
    )
}

export const WithAiTraffic: StoryFn<typeof ContentAutopilotTraffic> = () => <TrafficWithGoal />
WithAiTraffic.decorators = [queryHandlers({ hasAiTraffic: true })]

export const NoAiTraffic: StoryFn<typeof ContentAutopilotTraffic> = () => (
    <div className="p-6">
        <ContentAutopilotTraffic />
    </div>
)
NoAiTraffic.decorators = [queryHandlers({ hasAiTraffic: false })]
