import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { BreakdownFilter } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { InsightTooltip } from './InsightTooltip'
import { SeriesDatum } from './insightTooltipUtils'

const EN_DASH = '–'

const eventBreakdown: BreakdownFilter = { breakdown: '$event', breakdown_type: 'event_metadata' }

function renderTooltip(seriesData: SeriesDatum[], breakdownFilter: BreakdownFilter): HTMLElement {
    const { container } = render(
        <InsightTooltip
            date="2024-05-29"
            timezone="UTC"
            seriesData={seriesData}
            breakdownFilter={breakdownFilter}
            renderCount={(value) => `${value}`}
            renderSeries={(value) => value}
        />
    )
    return container
}

describe('InsightTooltip column layout', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // Regression: each breakdown row holds one series with its own `order`; the single value column
    // used to be keyed off one row's `order`, blanking every other row to an en-dash.
    it('shows each breakdown value when every row holds a single distinct series', () => {
        const seriesData: SeriesDatum[] = [
            {
                id: 0,
                dataIndex: 0,
                datasetIndex: 0,
                order: 0,
                breakdown_value: '$pageview',
                label: '$pageview',
                color: '#1d4aff',
                count: 94,
            },
            {
                id: 1,
                dataIndex: 0,
                datasetIndex: 1,
                order: 2,
                breakdown_value: '$rageclick',
                label: '$rageclick',
                color: '#621da6',
                count: 5,
            },
        ]

        const container = renderTooltip(seriesData, eventBreakdown)

        expect(container.textContent).toContain('94')
        expect(container.textContent).toContain('5')
        expect(container.textContent).not.toContain(EN_DASH)
    })

    // Regression: columns were seeded from the longest row only, so an `order` absent from it
    // (here order 2, present only in the Safari row) was dropped to an en-dash.
    it('renders a column for every series order across breakdown rows', () => {
        const seriesData: SeriesDatum[] = [
            { id: 0, dataIndex: 0, datasetIndex: 0, order: 0, breakdown_value: 'Chrome', label: 'A', count: 10 },
            { id: 1, dataIndex: 0, datasetIndex: 1, order: 1, breakdown_value: 'Chrome', label: 'B', count: 20 },
            { id: 2, dataIndex: 0, datasetIndex: 2, order: 1, breakdown_value: 'Safari', label: 'B', count: 5 },
            { id: 3, dataIndex: 0, datasetIndex: 3, order: 2, breakdown_value: 'Safari', label: 'C', count: 7 },
        ]

        const container = renderTooltip(seriesData, eventBreakdown)

        // The previously-dropped value (Safari / order 2) is now rendered.
        expect(container.textContent).toContain('7')
        expect(container.textContent).toContain('10')
        expect(container.textContent).toContain('20')
        expect(container.textContent).toContain('5')
    })
})
