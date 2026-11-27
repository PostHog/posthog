import { Meta, StoryObj } from '@storybook/react'

import { buildTheme } from 'lib/charts/utils/theme'

import { mswDecorator } from '~/mocks/browser'
import {
    MCPDashboardQuery,
    MCPDashboardSection,
    MCPDashboardSectionResult,
    NodeKind,
} from '~/queries/schema/schema-general'

import { MCPAnalyticsLeaderboardHome } from '../leaderboardHome/MCPAnalyticsLeaderboardHome'
import { type KPIData, type KPIMetric } from '../mcpDashboardOverviewLogic'
import { KpiTiles } from './KpiTiles'

function metric(value: number, previousValue: number, sparkline: number[], goodDirection: 'up' | 'down'): KPIMetric {
    return {
        value,
        previousValue,
        deltaPct: previousValue ? ((value - previousValue) / previousValue) * 100 : null,
        sparkline,
        sparklineLabels: sparkline.map((_, i) => `2026-06-${String(10 + i).padStart(2, '0')} 00:00:00`),
        goodDirection,
    }
}

const KPIS: KPIData = {
    sessions: metric(2480, 2210, [320, 340, 355, 372, 360, 388, 401], 'up'),
    toolCalls: metric(31420, 27800, [4100, 4300, 4500, 4720, 4600, 4900, 5100], 'up'),
    errorRatePct: metric(3.6, 4.1, [4.2, 3.9, 3.5, 3.3, 3.7, 3.4, 3.2], 'down'),
    p95LatencyMs: metric(2240, 2380, [1900, 2050, 2100, 2080, 2200, 2150, 2240], 'down'),
    users: metric(1840, 1655, [262, 271, 280, 294, 288, 301, 312], 'up'),
}

const meta: Meta = {
    title: 'Scenes-App/MCP Analytics/Dashboard Cards',
    parameters: { layout: 'padded' },
    decorators: [
        (Story) => (
            <div data-quill>
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj

export const KeyMetrics: Story = {
    render: () => (
        <div className="w-[960px]">
            <KpiTiles
                kpis={KPIS}
                intentClusterCount={metric(6, 0, [], 'up')}
                kpisLoading={false}
                usersLoading={false}
                kpisLoaded
                usersLoaded
                showIntentClusters
                theme={buildTheme()}
                interval="day"
                incompleteTail={false}
            />
        </div>
    ),
}

export const KeyMetricsInProgressBucket: Story = {
    render: () => (
        <div className="w-[960px]">
            <KpiTiles
                kpis={KPIS}
                intentClusterCount={metric(6, 0, [], 'up')}
                kpisLoading={false}
                usersLoading={false}
                kpisLoaded
                usersLoaded
                showIntentClusters
                theme={buildTheme()}
                interval="day"
                incompleteTail
            />
        </div>
    ),
}

export const KeyMetricsLoading: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    render: () => (
        <div className="w-[960px]">
            <KpiTiles
                kpis={KPIS}
                intentClusterCount={metric(6, 0, [], 'up')}
                kpisLoading
                usersLoading
                kpisLoaded={false}
                usersLoaded={false}
                showIntentClusters
                theme={buildTheme()}
                interval="day"
                incompleteTail={false}
            />
        </div>
    ),
}

export const KeyMetricsEmptyRange: Story = {
    render: () => (
        <div className="w-[960px]">
            <KpiTiles
                kpis={{
                    sessions: metric(0, 0, [], 'up'),
                    toolCalls: metric(0, 0, [], 'up'),
                    errorRatePct: metric(0, 0, [], 'down'),
                    p95LatencyMs: metric(0, 0, [], 'down'),
                    users: metric(0, 0, [], 'up'),
                }}
                intentClusterCount={metric(0, 0, [], 'up')}
                kpisLoading={false}
                usersLoading={false}
                kpisLoaded
                usersLoaded
                showIntentClusters
                theme={buildTheme()}
                interval="day"
                incompleteTail={false}
            />
        </div>
    ),
}

export const KeyMetricsLoadError: Story = {
    render: () => (
        <div className="w-[960px]">
            <KpiTiles
                kpis={KPIS}
                intentClusterCount={metric(6, 0, [], 'up')}
                kpisLoading={false}
                usersLoading={false}
                kpisLoaded
                usersLoaded
                kpisFailed
                onRetryKpis={() => {}}
                showIntentClusters
                theme={buildTheme()}
                interval="day"
                incompleteTail={false}
            />
        </div>
    ),
}

// The leaderboard also sends queries of other kinds, such as First Look's EventsQuery.
function answerDashboardSections(
    answer: (section: MCPDashboardSection) => MCPDashboardSectionResult,
    otherQueries: [number, object]
): Story {
    return {
        decorators: [
            mswDecorator({
                post: {
                    '/api/environments/:team_id/query/:kind': async ({ request }) => {
                        const { query } = (await request.json()) as { query: MCPDashboardQuery | { kind: string } }
                        if (query.kind !== NodeKind.MCPDashboardQuery) {
                            return otherQueries
                        }
                        return [
                            200,
                            {
                                results: Object.fromEntries(
                                    (query as MCPDashboardQuery).sections.map((section) => [section, answer(section)])
                                ),
                            },
                        ]
                    },
                },
            }),
        ],
        render: () => (
            <div className="w-[960px]">
                <MCPAnalyticsLeaderboardHome />
            </div>
        ),
    }
}

const UNKNOWN_MODEL_SECTIONS: Partial<Record<MCPDashboardSection, unknown[]>> = {
    [MCPDashboardSection.ModelRows]: [{ model: 'Unknown', total_calls: 100 }],
    [MCPDashboardSection.Model]: [['2026-06-07', 'Unknown', 100]],
}

export const LeaderboardUnknownModels: Story = answerDashboardSections(
    (section) => ({ results: UNKNOWN_MODEL_SECTIONS[section] ?? [] }),
    [200, { results: [] }]
)

const SECTIONS_THAT_LOAD = [
    MCPDashboardSection.Kpis,
    MCPDashboardSection.PeriodTotals,
    MCPDashboardSection.ToolRows,
    MCPDashboardSection.SessionRows,
]

export const LeaderboardLoadError: Story = answerDashboardSections(
    (section) => (SECTIONS_THAT_LOAD.includes(section) ? { results: [] } : { error: 'Query timed out' }),
    [504, { detail: 'Query timed out' }]
)
