import { cleanup, fireEvent, render } from '@testing-library/react'

import { dragSelection, getHogChart, hoverAtIndex, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { initKeaTests } from '~/test/init'

import { errorTrackingVolumeSparklineLogic } from './errorTrackingVolumeSparklineLogic'
import type { SparklineData, SparklineEvent } from './types'
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

const SPARKLINE_KEY = 'test-volume-sparkline'

function renderChart(props: Partial<React.ComponentProps<typeof VolumeSparkline>> = {}): HTMLElement {
    const { container } = render(
        <VolumeSparkline sparklineKey={SPARKLINE_KEY} data={buildData()} layout="detailed" xAxis="full" {...props} />
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

        // Pins quill's contract of normalizing the drag indices before invoking the callback —
        // the component itself no longer orders them.
        it('produces the same range when the drag direction is reversed', () => {
            const onRangeSelect = jest.fn()
            const data = buildData()
            const wrapper = renderChart({ data, onRangeSelect })

            dragSelection(wrapper, 3, 1, data.length)

            expect(onRangeSelect).toHaveBeenCalledWith(data[1].date, new Date(data[3].date.getTime() + BUCKET_MS))
        })

        it('does not fire when every bucket carries the same timestamp (placeholder data)', () => {
            const onRangeSelect = jest.fn()
            const date = new Date('2024-01-01T00:00:00.000Z')
            const data: SparklineData = [0, 1, 2, 3, 4].map(() => ({ date, value: 0 }))
            const wrapper = renderChart({ data, onRangeSelect })

            dragSelection(wrapper, 1, 3, data.length)

            expect(onRangeSelect).not.toHaveBeenCalled()
        })

        it('does not fire when no handler is passed', () => {
            const data = buildData()
            const wrapper = renderChart({ data, onRangeSelect: undefined })

            expect(() => dragSelection(wrapper, 1, 3, data.length)).not.toThrow()
        })
    })

    describe('bucket clicks', () => {
        it('selects the clicked bucket using its start and end boundaries', () => {
            const onRangeSelect = jest.fn()
            const data = buildData({ 3: { date: new Date('2024-01-01T04:00:00.000Z') } })
            const wrapper = renderChart({ data, onBucketClick: onRangeSelect })

            hoverAtIndex(wrapper, 2, data.length)
            fireEvent.click(wrapper)

            expect(onRangeSelect).toHaveBeenCalledWith(data[2].date, data[3].date)
            expect(wrapper.classList.contains('cursor-pointer')).toBe(true)
        })
    })

    describe('spike clicks', () => {
        it('fires onSpikeClick with the viewport cursor position when a flagged bucket is clicked', () => {
            const onSpikeClick = jest.fn()
            const data = buildData({ 2: { isSpike: true, color: 'var(--brand-red)' } })
            const { container } = render(
                <VolumeSparkline
                    sparklineKey={SPARKLINE_KEY}
                    data={data}
                    layout="detailed"
                    xAxis="full"
                    onSpikeClick={onSpikeClick}
                />
            )
            const wrapper = getHogChart(container).element

            hoverAtIndex(wrapper, 2, data.length)
            // On the outer container, past the chart's own wrapper-level handlers, so the hover
            // index survives — this is the viewport position the popover should anchor to.
            fireEvent.mouseMove(container.firstElementChild as HTMLElement, { clientX: 123, clientY: 45 })
            fireEvent.click(wrapper)

            expect(onSpikeClick).toHaveBeenCalledTimes(1)
            expect(onSpikeClick).toHaveBeenCalledWith(data[2], 123, 45)
        })

        it('prefers onSpikeClick over onBucketClick when a flagged bucket is clicked', () => {
            const onBucketClick = jest.fn()
            const onSpikeClick = jest.fn()
            const data = buildData({ 2: { isSpike: true, color: 'var(--brand-red)' } })
            const { container } = render(
                <VolumeSparkline
                    sparklineKey={SPARKLINE_KEY}
                    data={data}
                    layout="detailed"
                    xAxis="full"
                    onBucketClick={onBucketClick}
                    onSpikeClick={onSpikeClick}
                />
            )
            const wrapper = getHogChart(container).element

            hoverAtIndex(wrapper, 2, data.length)
            fireEvent.mouseMove(container.firstElementChild as HTMLElement, { clientX: 123, clientY: 45 })
            fireEvent.click(wrapper)

            expect(onSpikeClick).toHaveBeenCalledTimes(1)
            expect(onSpikeClick).toHaveBeenCalledWith(data[2], 123, 45)
            expect(onBucketClick).not.toHaveBeenCalled()
        })

        it('does not fire onSpikeClick for an ordinary (non-spike) bucket', () => {
            const onSpikeClick = jest.fn()
            // A spike elsewhere enables the handler (`hasSpikes`); the click lands on an
            // unflagged bucket.
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

    describe('spike stripes', () => {
        const SPIKE = { isSpike: true, color: 'var(--brand-yellow)' }

        function renderStripes(data: SparklineData): HTMLElement[] {
            const { container } = render(
                <VolumeSparkline sparklineKey={SPARKLINE_KEY} data={data} layout="detailed" xAxis="full" />
            )
            return Array.from(
                container.querySelectorAll<HTMLElement>('[data-attr="error-tracking-volume-spike-stripes"]')
            )
        }

        it('overlays one striped element per spike bucket', () => {
            expect(renderStripes(buildData({ 1: SPIKE, 3: SPIKE }))).toHaveLength(2)
        })

        it('overlays nothing when no bucket is a spike', () => {
            expect(renderStripes(buildData())).toHaveLength(0)
        })

        // The overlay mirrors quill's `minBarSize` flooring, which quill skips for a zero bucket —
        // so the overlay must too, or it stripes empty plot.
        it('overlays nothing for a spike bucket with no occurrences', () => {
            expect(renderStripes(buildData({ 2: { ...SPIKE, value: 0 } }))).toHaveLength(0)
        })

        it('places each overlay over its own bucket, in bucket order', () => {
            const [first, second] = renderStripes(buildData({ 1: SPIKE, 3: SPIKE }))

            expect(parseFloat(first.style.left)).toBeLessThan(parseFloat(second.style.left))
            expect(parseFloat(first.style.width)).toBeGreaterThan(0)
            expect(parseFloat(first.style.height)).toBeGreaterThan(0)
        })
    })

    describe('bar hover reporting', () => {
        it('publishes the hovered bin to the logic', () => {
            const data = buildData()
            const wrapper = renderChart({ data })

            hoverAtIndex(wrapper, 2, data.length)

            expect(errorTrackingVolumeSparklineLogic({ sparklineKey: SPARKLINE_KEY }).values.hoverSelection).toEqual({
                kind: 'bin',
                index: 2,
                datum: data[2],
            })
        })

        it('clears the hover when the chart unmounts', () => {
            // Keep the logic alive past the chart teardown, like a parent still rendering from it.
            const logic = errorTrackingVolumeSparklineLogic({ sparklineKey: SPARKLINE_KEY })
            const unmountLogic = logic.mount()
            const data = buildData()
            const { container, unmount } = render(
                <VolumeSparkline sparklineKey={SPARKLINE_KEY} data={data} layout="detailed" xAxis="full" />
            )
            hoverAtIndex(getHogChart(container).element, 2, data.length)
            expect(logic.values.hoverSelection).not.toBeNull()

            unmount()

            expect(logic.values.hoverSelection).toBeNull()
            unmountLogic()
        })
    })

    describe('event marker hover', () => {
        const data = buildData()
        const firstSeen: SparklineEvent<string> = { id: 'first_seen', date: data[1].date, payload: 'First Seen' }
        const lastSeen: SparklineEvent<string> = { id: 'last_seen', date: data[3].date, payload: 'Last Seen' }

        function renderWithEvents(events: SparklineEvent<string>[]): {
            container: HTMLElement
            rerenderWith: (next: SparklineEvent<string>[]) => void
        } {
            const { container, rerender } = render(
                <VolumeSparkline
                    sparklineKey={SPARKLINE_KEY}
                    data={data}
                    layout="detailed"
                    xAxis="full"
                    events={events}
                />
            )
            return {
                container,
                rerenderWith: (next) =>
                    rerender(
                        <VolumeSparkline
                            sparklineKey={SPARKLINE_KEY}
                            data={data}
                            layout="detailed"
                            xAxis="full"
                            events={next}
                        />
                    ),
            }
        }

        function hoverFirstPill(container: HTMLElement): void {
            fireEvent.mouseEnter(container.querySelectorAll('[data-attr="error-tracking-volume-event-label"]')[0])
        }

        it('publishes the hovered event to the logic', () => {
            const { container } = renderWithEvents([firstSeen, lastSeen])

            hoverFirstPill(container)

            expect(errorTrackingVolumeSparklineLogic({ sparklineKey: SPARKLINE_KEY }).values.hoverSelection).toEqual({
                kind: 'event',
                event: firstSeen,
            })
        })

        // React fires no `onMouseLeave` on unmount, so without cleanup the removed event stays in
        // `hoverSelection` and keeps the bar hover paused.
        it.each([
            { name: 'the hovered event drops out of the list', remaining: [lastSeen] },
            { name: 'every event disappears at once', remaining: [] },
        ])('clears the hover when $name', ({ remaining }) => {
            const { container, rerenderWith } = renderWithEvents([firstSeen, lastSeen])
            hoverFirstPill(container)

            rerenderWith(remaining)

            expect(errorTrackingVolumeSparklineLogic({ sparklineKey: SPARKLINE_KEY }).values.hoverSelection).toBeNull()
        })
    })
})
