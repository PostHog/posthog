import { cleanup, fireEvent, render } from '@testing-library/react'

import { dragSelection, getHogChart, hoverAtIndex, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { initKeaTests } from '~/test/init'

import type { SparklineData } from './types'
import { VolumeSparkline } from './VolumeSparkline'

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

const BUCKET_MS = 60 * 60 * 1000 // 1 hour, matches the fixture spacing below

function buildData(overrides: Partial<Record<number, Partial<SparklineData[number]>>> = {}): SparklineData {
    const base = Date.parse('2024-01-01T00:00:00.000Z')
    return [0, 1, 2, 3, 4].map((index) => ({
        date: new Date(base + index * BUCKET_MS),
        value: 10,
        ...overrides[index],
    }))
}

function renderChart(props: Partial<React.ComponentProps<typeof VolumeSparkline>> = {}): HTMLElement {
    const { container } = render(
        <VolumeSparkline
            sparklineKey="test-volume-sparkline"
            data={buildData()}
            layout="detailed"
            xAxis="full"
            {...props}
        />
    )
    return getHogChart(container).element
}

describe('VolumeSparkline', () => {
    describe('drag-to-zoom', () => {
        it('widens the selection to the end of the last dragged bucket', () => {
            const onRangeSelect = jest.fn()
            const data = buildData()
            const wrapper = renderChart({ data, onRangeSelect })

            dragSelection(wrapper, 1, 3, data.length)

            expect(onRangeSelect).toHaveBeenCalledWith(data[1].date, new Date(data[3].date.getTime() + BUCKET_MS))
        })

        it('produces the same range when the drag direction is reversed', () => {
            const onRangeSelect = jest.fn()
            const data = buildData()
            const wrapper = renderChart({ data, onRangeSelect })

            dragSelection(wrapper, 3, 1, data.length)

            expect(onRangeSelect).toHaveBeenCalledWith(data[1].date, new Date(data[3].date.getTime() + BUCKET_MS))
        })

        it('does not fire when no handler is passed', () => {
            const data = buildData()
            const wrapper = renderChart({ data, onRangeSelect: undefined })

            expect(() => dragSelection(wrapper, 1, 3, data.length)).not.toThrow()
        })
    })

    describe('spike clicks', () => {
        it('fires onSpikeClick when a flagged bucket is clicked', () => {
            const onSpikeClick = jest.fn()
            const data = buildData({ 2: { isSpike: true, color: 'var(--brand-red)' } })
            const wrapper = renderChart({ data, onSpikeClick })

            hoverAtIndex(wrapper, 2, data.length)
            fireEvent.click(wrapper)

            expect(onSpikeClick).toHaveBeenCalledTimes(1)
            expect(onSpikeClick).toHaveBeenCalledWith(data[2], expect.any(Number), expect.any(Number))
        })

        it('does not fire onSpikeClick for an ordinary (non-spike) bucket', () => {
            const onSpikeClick = jest.fn()
            // One spike elsewhere in the data enables the click handler at all (`hasSpikes`); the
            // click itself lands on an unflagged bucket.
            const data = buildData({ 2: { isSpike: true, color: 'var(--brand-red)' } })
            const wrapper = renderChart({ data, onSpikeClick })

            hoverAtIndex(wrapper, 0, data.length)
            fireEvent.click(wrapper)

            expect(onSpikeClick).not.toHaveBeenCalled()
        })

        it('never fires when no bucket in the data is flagged as a spike', () => {
            const onSpikeClick = jest.fn()
            const data = buildData()
            const wrapper = renderChart({ data, onSpikeClick })

            hoverAtIndex(wrapper, 2, data.length)
            fireEvent.click(wrapper)

            expect(onSpikeClick).not.toHaveBeenCalled()
        })
    })
})
