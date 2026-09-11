import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ensureJsdom } from '@posthog/quill-charts/testing'

import type { MetricsHistogramQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { HeatmapPanel } from './HeatmapPanel'

const response = (overrides?: Partial<MetricsHistogramQueryResponse>): MetricsHistogramQueryResponse =>
    ({
        kind: 'MetricsHistogramQueryResponse',
        times: ['2026-08-01T10:00:00Z', '2026-08-01T11:00:00Z'],
        bounds: [0.1, 0.5, 1],
        counts: [
            [5, 3],
            [2, 8],
            [1, 0],
        ],
        ...overrides,
    }) as MetricsHistogramQueryResponse

describe('HeatmapPanel', () => {
    beforeEach(() => {
        ensureJsdom()
        initKeaTests()
    })

    afterEach(() => cleanup())

    it('renders the y-axis bounds formatted with the unit', () => {
        render(<HeatmapPanel response={response()} unit="s" />)
        expect(screen.getByText('100 ms')).toBeInTheDocument()
        expect(screen.getByText('500 ms')).toBeInTheDocument()
        expect(screen.getByText('1 s')).toBeInTheDocument()
    })

    it('renders the time columns', () => {
        render(<HeatmapPanel response={response()} unit="s" />)
        expect(screen.getByText('1 Aug 10:00')).toBeInTheDocument()
        expect(screen.getByText('1 Aug 11:00')).toBeInTheDocument()
    })

    it('shows the empty state when no cell has a count', () => {
        render(
            <HeatmapPanel
                response={response({
                    counts: [
                        [0, 0],
                        [0, 0],
                        [0, 0],
                    ],
                })}
                unit="s"
            />
        )
        expect(screen.getByText(/No data for this metric/)).toBeInTheDocument()
    })

    it('formats bounds without a unit as compact numbers', () => {
        render(<HeatmapPanel response={response({ bounds: [10, 2000] })} />)
        expect(screen.getByText('10')).toBeInTheDocument()
        expect(screen.getByText('2K')).toBeInTheDocument()
    })
})
