import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TrendsVisualizer } from '../../src/ui-apps/components/TrendsVisualizer'
import type { ChartDisplayType, TrendsResult } from '../../src/ui-apps/components/types'

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

    // The line/bar mode toggle (native <select>) only appears for time-series display types;
    // ActionsBarValue is always a horizontal bar of aggregated totals, so it has none.
    it.each<{ display: ChartDisplayType; results: TrendsResult; comboboxCount: number }>([
        {
            display: 'ActionsBarValue',
            results: [
                { label: 'Chrome', aggregated_value: 100, data: [], days: [] },
                { label: 'Firefox', aggregated_value: 80, data: [], days: [] },
                { label: 'Safari', aggregated_value: 60, data: [], days: [] },
            ],
            comboboxCount: 0,
        },
        {
            display: 'ActionsLineGraph',
            results: [{ label: 'Pageviews', data: [10, 20, 30], days: ['2024-01-01', '2024-01-02', '2024-01-03'] }],
            comboboxCount: 1,
        },
    ])(
        'renders a quill canvas for $display with $comboboxCount mode toggle(s)',
        ({ display, results, comboboxCount }) => {
            render(<TrendsVisualizer query={{ kind: 'TrendsQuery', trendsFilter: { display } }} results={results} />)

            expect(document.querySelector('canvas')).toBeTruthy()
            expect(screen.queryAllByRole('combobox')).toHaveLength(comboboxCount)
        }
    )
})
