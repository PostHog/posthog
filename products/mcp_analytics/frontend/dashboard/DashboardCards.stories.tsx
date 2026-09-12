import { Meta, StoryObj } from '@storybook/react'

import { type ChartTheme } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'

import { mswDecorator } from '~/mocks/browser'
import { MCPModelBreakdownQuery } from '~/queries/schema/schema-general'

import { MCPAnalyticsDashboardOverview } from '../MCPAnalyticsDashboardOverview'
import {
    type DailyActivity,
    type HarnessRow,
    type KPIData,
    type KPIMetric,
    type ModelRow,
    type NotableSession,
    type ToolDailySeries,
    type ToolRow,
} from '../mcpDashboardOverviewLogic'
import { ActivityChart } from './ActivityChart'
import { HarnessBarChart } from './HarnessBarChart'
import { KpiTiles } from './KpiTiles'
import { ModelBarChart } from './ModelBarChart'
import { NotableSessionsTable } from './NotableSessionsTable'
import { ToolErrorRateChart } from './ToolErrorRateChart'
import { ToolUsageChart } from './ToolUsageChart'

const DAYS = ['Jun 1', 'Jun 2', 'Jun 3', 'Jun 4', 'Jun 5', 'Jun 6', 'Jun 7']

const DAILY_ACTIVITY: DailyActivity = {
    labels: DAYS,
    successes: [4180, 4360, 4560, 4430, 4720, 4920, 5130],
    errors: [120, 140, 160, 170, 180, 176, 168],
}

// The shape the in-progress stories exist for: the last bucket is a few hours into the day, so its
// counts sit far below its neighbours. Dashing it is what stops that reading as a collapse.
const DAILY_ACTIVITY_PARTIAL_TAIL: DailyActivity = {
    labels: DAYS,
    successes: [4180, 4360, 4560, 4430, 4720, 4920, 1680],
    errors: [120, 140, 160, 170, 180, 176, 54],
}

const TOOL_DAILY: ToolDailySeries = {
    labels: DAYS,
    tools: [
        { tool: 'exec', data: [720, 760, 800, 740, 820, 880, 910] },
        { tool: 'execute-sql', data: [210, 230, 250, 240, 260, 280, 300] },
        { tool: 'read-data-schema', data: [110, 120, 95, 130, 140, 150, 120] },
        { tool: 'query-trends', data: [60, 80, 70, 90, 100, 80, 110] },
    ],
}

const TOOL_ROWS: ToolRow[] = [
    { tool: 'cohort-create', total_calls: 95, errors: 6, error_rate_pct: 28, p95_duration_ms: 1620 },
    { tool: 'execute-sql', total_calls: 1480, errors: 144, error_rate_pct: 13, p95_duration_ms: 3525 },
    { tool: 'exec', total_calls: 5200, errors: 208, error_rate_pct: 9.3, p95_duration_ms: 2290 },
    { tool: 'insight-create', total_calls: 410, errors: 8, error_rate_pct: 2, p95_duration_ms: 727 },
    { tool: 'query-trends', total_calls: 540, errors: 5, error_rate_pct: 1, p95_duration_ms: 2122 },
    { tool: 'read-data-schema', total_calls: 760, errors: 3, error_rate_pct: 0.4, p95_duration_ms: 1298 },
]

const HARNESS_ROWS: HarnessRow[] = [
    { category: 'OpenAI Codex', total_calls: 4200, errors: 84, error_rate_pct: 2, sessions: 600 },
    { category: 'Claude Code', total_calls: 2800, errors: 112, error_rate_pct: 4, sessions: 400 },
    { category: 'Claude Agent SDK', total_calls: 1600, errors: 48, error_rate_pct: 3, sessions: 200 },
    { category: 'Cursor', total_calls: 1200, errors: 24, error_rate_pct: 2, sessions: 180 },
    { category: 'Cowork', total_calls: 800, errors: 8, error_rate_pct: 1, sessions: 120 },
    { category: 'Claude.ai', total_calls: 400, errors: 12, error_rate_pct: 3, sessions: 80 },
    { category: 'Other', total_calls: 200, errors: 10, error_rate_pct: 5, sessions: 50 },
]

const MODEL_ROWS: ModelRow[] = [
    { model: 'claude-sonnet-5', total_calls: 4200 },
    { model: 'gpt-5.6-sol', total_calls: 3100 },
    { model: 'claude-opus-4', total_calls: 2200 },
    { model: 'Unknown', total_calls: 1400 },
    { model: 'gemini-2.5-pro', total_calls: 900 },
    { model: 'gpt-4o', total_calls: 750 },
    { model: 'Other', total_calls: 580 },
    { model: 'grok-3', total_calls: 320 },
]

const ALL_MODEL_ROWS: ModelRow[] = [
    ...MODEL_ROWS.filter((row) => row.model !== 'Unknown' && row.model !== 'Other'),
    ...Array.from({ length: 58 }, (_, index) => ({
        model: `example-provider/model-with-a-long-version-name-${String(index + 1).padStart(2, '0')}`,
        total_calls: 10,
    })),
]

const modelPagesDecorator = mswDecorator({
    post: {
        '/api/environments/:team_id/query/:kind': async ({ request }) => {
            const { query } = (await request.json()) as { query: MCPModelBreakdownQuery }
            const offset = query.offset ?? 0
            const limit = query.limit ?? 50
            return [
                200,
                {
                    results: ALL_MODEL_ROWS.slice(offset, offset + limit),
                    hasMore: offset + limit < ALL_MODEL_ROWS.length,
                },
            ]
        },
    },
})

const NOTABLE_SESSIONS: NotableSession[] = [
    {
        rule: 'worst_error_rate',
        label: 'Worst error rate at high volume',
        session: {
            session_id: '0193f2a1aaaabbbbcccc000000000001',
            tool_calls: 42,
            errors: 18,
            error_rate_pct: 42.9,
            duration_seconds: 610,
            distinct_tools: 7,
            last_seen: '',
        },
    },
    {
        rule: 'all_fail',
        label: 'Every call failed, likely an auth scope issue',
        session: {
            session_id: '0193f2a1aaaabbbbcccc000000000002',
            tool_calls: 6,
            errors: 6,
            error_rate_pct: 100,
            duration_seconds: 95,
            distinct_tools: 2,
            last_seen: '',
        },
    },
    {
        rule: 'exemplar',
        label: 'Concise success',
        session: {
            session_id: '0193f2a1aaaabbbbcccc000000000003',
            tool_calls: 31,
            errors: 0,
            error_rate_pct: 0,
            duration_seconds: 240,
            distinct_tools: 11,
            last_seen: '',
        },
    },
]

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

function withTheme(render: (theme: ChartTheme) => JSX.Element): () => JSX.Element {
    // Charts size themselves from their container via ResizeObserver, so the wrapper needs a
    // definite width (not just max-width) — otherwise the card collapses in the shrink-to-fit
    // snapshot runtime. Mirrors quill's own `Stage` story helper.
    return () => <div className="w-[680px]">{render(buildTheme())}</div>
}

export const KeyMetrics: Story = {
    render: () => (
        <div className="w-[960px]">
            <KpiTiles
                kpis={KPIS}
                users={metric(1840, 1655, [], 'up')}
                intentClusterCount={metric(6, 0, [], 'up')}
                kpisLoading={false}
                usersLoading={false}
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
                users={metric(1840, 1655, [], 'up')}
                intentClusterCount={metric(6, 0, [], 'up')}
                kpisLoading={false}
                usersLoading={false}
                showIntentClusters
                theme={buildTheme()}
                interval="day"
                incompleteTail
            />
        </div>
    ),
}

export const DailyCallsAndErrors: Story = {
    render: withTheme((theme) => (
        <ActivityChart
            daily={DAILY_ACTIVITY}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail={false}
        />
    )),
}

export const DailyCallsAndErrorsInProgressBucket: Story = {
    render: withTheme((theme) => (
        <ActivityChart
            daily={DAILY_ACTIVITY_PARTIAL_TAIL}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail
        />
    )),
}

export const ShareByHarness: Story = {
    render: withTheme((theme) => <HarnessBarChart rows={HARNESS_ROWS} loading={false} theme={theme} />),
}

export const ShareByHarnessNarrow: Story = {
    render: () => (
        <div className="w-80">
            <HarnessBarChart
                rows={[
                    {
                        category: 'Example custom client with a very long name',
                        total_calls: 1,
                        errors: 0,
                        error_rate_pct: 0,
                        sessions: 1,
                    },
                    ...HARNESS_ROWS.toReversed(),
                    { category: 'Claude Code (VS Code)', total_calls: 140, errors: 7, error_rate_pct: 5, sessions: 20 },
                    { category: 'opencode', total_calls: 80, errors: 0, error_rate_pct: 0, sessions: 16 },
                    { category: 'Antigravity', total_calls: 40, errors: 0, error_rate_pct: 0, sessions: 8 },
                    { category: 'Grok', total_calls: 20, errors: 1, error_rate_pct: 5, sessions: 4 },
                ]}
                loading={false}
                theme={buildTheme()}
            />
        </div>
    ),
}

export const ShareByHarnessLoading: Story = {
    render: withTheme((theme) => <HarnessBarChart rows={[]} loading theme={theme} />),
}

export const ShareByHarnessEmpty: Story = {
    render: withTheme((theme) => <HarnessBarChart rows={[]} loading={false} theme={theme} />),
}

export const ShareByHarnessOtherOnly: Story = {
    render: withTheme((theme) => (
        <HarnessBarChart
            rows={[{ category: 'Other', total_calls: 15, errors: 0, error_rate_pct: 0, sessions: 3 }]}
            loading={false}
            theme={theme}
        />
    )),
}

export const ShareByModel: Story = {
    decorators: [modelPagesDecorator],
    render: withTheme((theme) => <ModelBarChart rows={MODEL_ROWS} theme={theme} />),
}

export const ShareByModelExpandedNarrow: Story = {
    decorators: [modelPagesDecorator],
    render: () => (
        <div className="w-80">
            <ModelBarChart rows={MODEL_ROWS} theme={buildTheme()} />
        </div>
    ),
}

export const ShareByModelLoadError: Story = {
    decorators: [
        mswDecorator({
            post: { '/api/environments/:team_id/query/:kind': [500, { detail: 'Could not load models' }] },
        }),
    ],
    render: withTheme((theme) => <ModelBarChart rows={MODEL_ROWS} theme={theme} />),
}

export const ShareByModelNarrow: Story = {
    render: () => (
        <div className="w-80">
            <ModelBarChart
                rows={[
                    { model: 'Other', total_calls: 30 },
                    { model: 'example-provider/model-with-a-long-version-name', total_calls: 4200 },
                    { model: 'gpt-5.6-sol', total_calls: 3100 },
                    { model: 'Unknown', total_calls: 1400 },
                    { model: 'example-model-c', total_calls: 800 },
                    { model: 'example-model-d', total_calls: 600 },
                    { model: 'example-model-e', total_calls: 400 },
                    { model: 'example-model-f', total_calls: 1 },
                ]}
                theme={buildTheme()}
            />
        </div>
    ),
}

export const ShareByModelLowCoverage: Story = {
    render: withTheme((theme) => (
        <ModelBarChart
            rows={[
                { model: 'Unknown', total_calls: 900 },
                { model: 'example-model', total_calls: 70 },
                { model: 'Other', total_calls: 30 },
            ]}
            theme={theme}
        />
    )),
}

export const ShareByModelFullCoverage: Story = {
    render: withTheme((theme) => <ModelBarChart rows={[{ model: 'example-model', total_calls: 100 }]} theme={theme} />),
}

export const ShareByModelUnknownOnly: Story = {
    render: withTheme((theme) => <ModelBarChart rows={[{ model: 'Unknown', total_calls: 100 }]} theme={theme} />),
}

export const ShareByModelEmpty: Story = {
    render: withTheme((theme) => <ModelBarChart rows={[]} theme={theme} />),
}

export const ErrorRateByTool: Story = {
    render: withTheme((theme) => <ToolErrorRateChart rows={TOOL_ROWS} loading={false} theme={theme} />),
}

export const DailyToolBreakdown: Story = {
    render: withTheme((theme) => (
        <ToolUsageChart data={TOOL_DAILY} loading={false} theme={theme} timezone="UTC" interval="day" />
    )),
}

export const FlaggedSessions: Story = {
    render: () => (
        <div className="w-[680px]">
            <NotableSessionsTable sessions={NOTABLE_SESSIONS} loading={false} />
        </div>
    ),
}

export const OverviewUnknownModels: Story = {
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { kind: string } }
                    return [
                        200,
                        {
                            results:
                                query.kind === 'MCPModelBreakdownQuery' ? [{ model: 'Unknown', total_calls: 100 }] : [],
                        },
                    ]
                },
            },
        }),
    ],
    render: () => <MCPAnalyticsDashboardOverview />,
}
