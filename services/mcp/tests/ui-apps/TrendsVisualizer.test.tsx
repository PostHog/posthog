import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TrendsVisualizer } from '../../src/ui-apps/components/TrendsVisualizer'
import type { TrendsResult } from '../../src/ui-apps/components/types'

describe('TrendsVisualizer', () => {
    it('shows an empty state when there are no results', () => {
        render(<TrendsVisualizer query={{ kind: 'TrendsQuery' }} results={[]} />)

        expect(screen.getByText('No data available')).toBeTruthy()
    })

    it('shows the aggregated total for BoldNumber display', () => {
        const results: TrendsResult = [{ label: 'Pageviews', aggregated_value: 42, data: [42] }]
        render(
            <TrendsVisualizer
                query={{ kind: 'TrendsQuery', trendsFilter: { display: 'BoldNumber' } }}
                results={results}
            />
        )

        // formatNumber(42) → '42' (toLocaleString fallback)
        expect(screen.getByText('42')).toBeTruthy()
    })

    it('renders a quill canvas chart for ActionsBarValue without a time-series mode toggle', () => {
        const results: TrendsResult = [
            { label: 'Chrome', aggregated_value: 100, data: [], days: [] },
            { label: 'Firefox', aggregated_value: 80, data: [], days: [] },
            { label: 'Safari', aggregated_value: 60, data: [], days: [] },
        ]
        render(
            <TrendsVisualizer
                query={{ kind: 'TrendsQuery', trendsFilter: { display: 'ActionsBarValue' } }}
                results={results}
            />
        )

        // Quill BarChart renders to a canvas element
        expect(document.querySelector('canvas')).toBeTruthy()
        // The time-series line/bar mode selector must NOT appear — ActionsBarValue is always a
        // horizontal bar of aggregated totals, not a time series
        expect(screen.queryByRole('combobox')).toBeNull()
    })

    it('renders a quill canvas chart with a line/bar mode toggle for time-series data', () => {
        const results: TrendsResult = [
            {
                label: 'Pageviews',
                data: [10, 20, 30],
                days: ['2024-01-01', '2024-01-02', '2024-01-03'],
            },
        ]
        render(
            <TrendsVisualizer
                query={{ kind: 'TrendsQuery', trendsFilter: { display: 'ActionsLineGraph' } }}
                results={results}
            />
        )

        // Mode toggle (native <select>) is shown for time-series display types
        expect(screen.getByRole('combobox')).toBeTruthy()
        // Quill chart renders to canvas
        expect(document.querySelector('canvas')).toBeTruthy()
    })
})
