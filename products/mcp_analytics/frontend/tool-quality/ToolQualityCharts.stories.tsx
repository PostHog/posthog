import { Meta, StoryObj } from '@storybook/react'

import { type ChartTheme } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'

import { DEFAULT_CHART_VIEWS, type DailyToolStat, buildDailyChartData } from '../mcpAnalyticsToolQualityLogic'
import { ToolQualityCharts } from './ToolQualityCharts'

const LABELS = [
    '2026-06-01 00:00:00',
    '2026-06-02 00:00:00',
    '2026-06-03 00:00:00',
    '2026-06-04 00:00:00',
    '2026-06-05 00:00:00',
    '2026-06-06 00:00:00',
    '2026-06-07 00:00:00',
]

const SETTLED_ROWS: DailyToolStat[] = LABELS.map((day, i) => {
    const calls = [820, 910, 880, 940, 1010, 990, 1060][i]
    const p50 = [180, 176, 190, 184, 178, 182, 188][i]
    return {
        day,
        calls,
        errors: [24, 31, 27, 33, 30, 28, 35][i],
        min: 12,
        p25: p50 / 2,
        p50,
        mean: p50 * 1.6,
        p75: p50 * 2.5,
        p95: [900, 940, 980, 920, 960, 910, 970][i],
        p99: [2100, 2200, 2350, 2180, 2260, 2140, 2300][i],
        max: 30000,
    }
})

const DAILY = buildDailyChartData(SETTLED_ROWS, LABELS)

// The shape the in-progress story exists for: the last bucket is a few hours into the day, so its
// counts sit far below its neighbours and its percentiles are computed off a thin sample.
const DAILY_PARTIAL_TAIL = buildDailyChartData(
    [
        ...SETTLED_ROWS.slice(0, -1),
        { ...SETTLED_ROWS[6], calls: 310, errors: 6, p50: 140, p95: 620, p99: 1180, max: 4000 },
    ],
    LABELS
)

const meta: Meta = {
    title: 'Scenes-App/MCP Analytics/Tool Quality Charts',
    // The tab lays the three charts side by side from `lg` up, so at the default 1280 snapshot
    // viewport each one is barely 400px wide and the dashed tail is hard to read. Snapshot wide.
    parameters: { layout: 'padded', testOptions: { viewport: { width: 1920, height: 720 } } },
}
export default meta

type Story = StoryObj

function withTheme(render: (theme: ChartTheme) => JSX.Element): () => JSX.Element {
    return function Render() {
        return <div data-quill>{render(buildTheme())}</div>
    }
}

export const SettledWindow: Story = {
    render: withTheme((theme) => (
        <ToolQualityCharts
            data={DAILY}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail={false}
            views={DEFAULT_CHART_VIEWS}
            onViewChange={() => {}}
        />
    )),
}

export const InProgressBucket: Story = {
    render: withTheme((theme) => (
        <ToolQualityCharts
            data={DAILY_PARTIAL_TAIL}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail
            views={DEFAULT_CHART_VIEWS}
            onViewChange={() => {}}
        />
    )),
}

export const AlternateViews: Story = {
    render: withTheme((theme) => (
        <ToolQualityCharts
            data={DAILY}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail={false}
            views={{ calls: 'percentage', successRate: 'log', latency: 'boxPlot' }}
            onViewChange={() => {}}
        />
    )),
}
