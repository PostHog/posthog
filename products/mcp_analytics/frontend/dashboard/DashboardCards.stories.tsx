import { Meta, StoryObj } from '@storybook/react'

import { type ChartTheme } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'

import {
    type DailyActivity,
    type HarnessRow,
    type KPIData,
    type KPIMetric,
    type NotableSession,
    type ToolDailySeries,
    type ToolRow,
} from '../mcpDashboardOverviewLogic'
import { ActivityChart } from './ActivityChart'
import { HarnessDonut } from './HarnessDonut'
import { KpiTiles } from './KpiTiles'
import { NotableSessionsTable } from './NotableSessionsTable'
import { ToolErrorRateChart } from './ToolErrorRateChart'
import { ToolUsageChart } from './ToolUsageChart'

const DAYS = ['Jun 1', 'Jun 2', 'Jun 3', 'Jun 4', 'Jun 5', 'Jun 6', 'Jun 7']

const DAILY_ACTIVITY: DailyActivity = {
    labels: DAYS,
    successes: [4180, 4360, 4560, 4430, 4720, 4920, 5130],
    errors: [120, 140, 160, 170, 180, 176, 168],
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
    { category: 'Claude Code', total_calls: 6200, errors: 240, error_rate_pct: 3.9, sessions: 820 },
    { category: 'Cursor', total_calls: 2100, errors: 96, error_rate_pct: 4.6, sessions: 410 },
    { category: 'OpenAI Codex', total_calls: 980, errors: 71, error_rate_pct: 7.2, sessions: 180 },
    { category: 'Claude.ai', total_calls: 760, errors: 22, error_rate_pct: 2.9, sessions: 240 },
    { category: 'VS Code', total_calls: 540, errors: 12, error_rate_pct: 2.2, sessions: 120 },
]

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
        label: 'Every call failed — likely auth scope',
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
        label: 'Exemplar — concise success',
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
                theme={buildTheme()}
            />
        </div>
    ),
}

export const DailyCallsAndErrors: Story = {
    render: withTheme((theme) => (
        <ActivityChart daily={DAILY_ACTIVITY} loading={false} theme={theme} timezone="UTC" interval="day" />
    )),
}

export const ShareByHarness: Story = {
    render: withTheme((theme) => <HarnessDonut rows={HARNESS_ROWS} loading={false} theme={theme} />),
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
