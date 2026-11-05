import { render } from '@testing-library/react'

import { findChart, setupChartTests } from '@posthog/quill-charts/testing'

import { buildTheme } from 'lib/charts/utils/theme'

import { DEFAULT_CHART_VIEWS, buildDailyChartData } from '../mcpAnalyticsToolQualityLogic'
import { ToolQualityCharts } from './ToolQualityCharts'

setupChartTests()

const LABELS = ['2026-06-01 00:00:00', '2026-06-02 00:00:00', '2026-06-03 00:00:00']

describe('ToolQualityCharts', () => {
    it.each([
        { range: 'hundredths of a percent', errorsPerDay: [500, 300, 100] },
        { range: 'thousandths of a percent', errorsPerDay: [100, 60, 20] },
    ])('gives each zoomed success rate tick its own label across $range', async ({ errorsPerDay }) => {
        const data = buildDailyChartData(
            LABELS.map((day, i) => ({ day, calls: 1_000_000, errors: errorsPerDay[i], p50: 1, p95: 1, p99: 1 })),
            LABELS
        )

        const { container } = render(
            <ToolQualityCharts
                data={data}
                loading={false}
                theme={buildTheme()}
                timezone="UTC"
                interval="day"
                incompleteTail={false}
                views={{ ...DEFAULT_CHART_VIEWS, successRate: 'zoom' }}
                latencyBoxes={data.latencyBoxes}
                onViewChange={() => {}}
            />
        )
        const scope = container.querySelector<HTMLElement>('[data-attr="mcp-tool-quality-success-rate-chart"]')
        const chart = await findChart({ scope: scope ?? undefined })

        const ticks = chart.yTicks()
        expect(ticks.length).toBeGreaterThan(1)
        expect(new Set(ticks).size).toBe(ticks.length)
    })
})
