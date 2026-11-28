import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { createDefaultTooltipAccessor, ensureJsdom, getChart, hoverUntilTooltip } from '@posthog/quill-charts/testing'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ContentAutopilotVisibilityChart } from './ContentAutopilotVisibilityChart'
import type { EngineVisibilityChart } from './visibilityChart'

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
})
