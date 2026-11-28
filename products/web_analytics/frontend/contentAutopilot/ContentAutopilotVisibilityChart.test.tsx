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

    it.each([
        ['only the last day', ['2026-10-30'], 1],
        ['days 10 and 12', ['2026-10-10', '2026-10-12'], 21],
    ])('starts a 30-day axis at the first day of data when there is data on %s', async (_name, withData, days) => {
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
            withData.flatMap((date) => [day(date, 'claude-web-search'), day(date, 'openai-web-search')]),
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
        await waitFor(() => expect(rendered.seriesCount).toBe(2))
        expect(chart.labels).toHaveLength(days)
        // The axis starts at the first day of data, not at the start of the range.
        await waitFor(() => expect(rendered.xTicks()[0]).toEqual(withData[0] === '2026-10-30' ? 'Oct 30' : 'Oct 10'))
    })
})
