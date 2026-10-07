import { cleanup, render } from '@testing-library/react'

import { clickAtIndex, getHogChart, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { initKeaTests } from '~/test/init'

import type { TracingSparklineData } from './tracingDataLogic'
import { TracingSparkline } from './TracingSparkline'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    initKeaTests()
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

const DATES = [
    '2024-01-01T00:00:00.000Z',
    '2024-01-01T01:00:00.000Z',
    '2024-01-01T02:00:00.000Z',
    '2024-01-01T03:00:00.000Z',
]
const SPARKLINE_DATA: TracingSparklineData = {
    dates: DATES,
    labels: DATES,
    data: [
        { name: 'checkout', values: [4, 5, 6, 7], color: 'data-color-1' },
        { name: 'search', values: [1, 2, 3, 4], color: 'data-color-2' },
    ],
}

const COMPARE = {
    fullStartMs: Date.parse(DATES[0]),
    fullEndMs: Date.parse(DATES[3]),
    currentWindow: { startMs: Date.parse(DATES[2]), endMs: Date.parse(DATES[3]) },
    previousWindow: { startMs: Date.parse(DATES[0]), endMs: Date.parse(DATES[1]) },
    onChange: jest.fn(),
}

function renderChart(props: Partial<React.ComponentProps<typeof TracingSparkline>> = {}): {
    element: HTMLElement
    onDateRangeChange: jest.Mock
} {
    const onDateRangeChange = jest.fn()
    const { container } = render(
        <TracingSparkline
            sparklineData={SPARKLINE_DATA}
            sparklineLoading={false}
            onDateRangeChange={onDateRangeChange}
            displayTimezone="UTC"
            {...props}
        />
    )
    return { element: getHogChart(container).element, onDateRangeChange }
}

describe('TracingSparkline', () => {
    describe('bar click', () => {
        it('narrows the range to the clicked bucket only', async () => {
            const { element, onDateRangeChange } = renderChart()

            await clickAtIndex(element, 1, DATES.length)

            expect(onDateRangeChange).toHaveBeenCalledWith(
                { date_from: DATES[1], date_to: DATES[2] },
                'sparkline_bar_click'
            )
        })

        it('ends the last bucket on the queried window, not on the next bucket', async () => {
            const currentDateTo = '2024-01-01T04:00:00.000Z'
            const { element, onDateRangeChange } = renderChart({ currentDateTo })

            await clickAtIndex(element, DATES.length - 1, DATES.length)

            expect(onDateRangeChange).toHaveBeenCalledWith(
                { date_from: DATES[3], date_to: currentDateTo },
                'sparkline_bar_click'
            )
        })

        it('does nothing while comparing time windows', async () => {
            const { element, onDateRangeChange } = renderChart({ compare: COMPARE, compareActive: true })

            await clickAtIndex(element, 1, DATES.length)

            expect(onDateRangeChange).not.toHaveBeenCalled()
        })

        it('does nothing while a comparison is active even without a custom window overlay', async () => {
            // Named time presets (previous period, yesterday, ...) have no draggable overlay, so
            // `compare` is undefined — the click must still be disabled via `compareActive`.
            const { element, onDateRangeChange } = renderChart({ compareActive: true })

            await clickAtIndex(element, 1, DATES.length)

            expect(onDateRangeChange).not.toHaveBeenCalled()
        })
    })
})
