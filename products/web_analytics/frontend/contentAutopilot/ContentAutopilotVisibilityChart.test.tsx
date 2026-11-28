import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { createDefaultTooltipAccessor, ensureJsdom, getChart, hoverUntilTooltip } from '@posthog/quill-charts/testing'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { AEOPromptDailyEngineStatsApi } from '../generated/api.schemas'
import { ContentAutopilotVisibilityChart } from './ContentAutopilotVisibilityChart'
import { type EngineVisibilityChart, engineVisibilityChart } from './visibilityChart'

const QUERY: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
}

const chartOver = (days: number): EngineVisibilityChart => {
    const labels = Array.from({ length: days }, (_, index) => `2026-10-${String(index + 1).padStart(2, '0')}`)
    return {
        labels,
        series: [
            { engine: 'claude-web-search', label: 'Claude', color: undefined, data: labels.map(() => 0.5) },
            { engine: 'openai-web-search', label: 'ChatGPT', color: undefined, data: labels.map(() => 0.25) },
        ],
    }
}

describe('ContentAutopilotVisibilityChart', () => {
    beforeEach(() => {
        ensureJsdom()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([1, 2, 10])('draws the chart from %s day(s) of data, with no note asking to wait', async (days) => {
        render(
            <ContentAutopilotVisibilityChart
                chart={chartOver(days)}
                metric="mentioned"
                onMetricChange={() => {}}
                query={QUERY}
                data-attr="visibility"
            />
        )

        const chart = getChart()
        await waitFor(() => expect(chart.seriesCount).toBe(2))
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, days - 1, days))
        await waitFor(() => expect(tooltip.rows()).toEqual(['Claude', 'ChatGPT']))
        expect(screen.queryByText(/waiting for more days/i)).toBeNull()
    })

    it('puts only the days with data on the axis of a 30-day range, one engine with a gap', async () => {
        const dates = Array.from({ length: 30 }, (_, index) => `2026-10-${String(index + 1).padStart(2, '0')}`)
        const day = (date: string, engine: string): AEOPromptDailyEngineStatsApi => ({
            date,
            engine,
            checks: 4,
            cited: 1,
            mentioned: 2,
            failed: 0,
            avg_position: 2,
        })
        const chart = engineVisibilityChart(
            [
                day('2026-10-05', 'claude-web-search'),
                day('2026-10-20', 'claude-web-search'),
                day('2026-10-20', 'openai-web-search'),
            ],
            dates,
            'mentioned'
        )
        render(
            <ContentAutopilotVisibilityChart
                chart={chart}
                metric="mentioned"
                onMetricChange={() => {}}
                query={QUERY}
                data-attr="visibility"
            />
        )

        const rendered = getChart()
        await waitFor(() => expect(rendered.xTicks()).toHaveLength(2))
        // ChatGPT has no answer on the first day, so its row is absent there rather than reading 0%.
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(rendered.element, 0, 2))
        await waitFor(() => expect(tooltip.rows()).toEqual(['Claude']))
    })
})
