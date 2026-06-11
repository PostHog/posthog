import { render } from '@testing-library/react'

import type { IndexedTrendResult } from 'scenes/trends/types'

import { NodeKind } from '~/queries/schema/schema-general'
import { CompareLabelType, EntityTypes } from '~/types'

import { handleStickinessChartClick, type StickinessChartClickDeps } from './handleStickinessChartClick'

// `IndexedTrendResult['days']` is declared `string[]`, but the backend serves
// stickiness "days" as integers. Centralize the cast so the test bodies stay clean.
const daysAsType = (nums: number[]): string[] => nums as unknown as string[]

function makeTrendResult(overrides: Partial<IndexedTrendResult> = {}): IndexedTrendResult {
    return {
        id: 0,
        seriesIndex: 0,
        colorIndex: 0,
        action: {
            id: '$pageview',
            type: EntityTypes.EVENTS,
            order: 0,
            name: '$pageview',
            days: daysAsType([1, 2, 3]),
        },
        label: '$pageview',
        count: 10,
        aggregated_value: 10,
        data: [5, 3, 2],
        labels: ['1 day', '2 days', '3 days'],
        days: daysAsType([1, 2, 3]),
        ...overrides,
    }
}

function keyFor(trendResult: IndexedTrendResult): string {
    return `${trendResult.id}`
}

function makeDeps(overrides: Partial<StickinessChartClickDeps> = {}): StickinessChartClickDeps {
    const trendResult = makeTrendResult()
    return {
        hasPersonsModal: true,
        interval: 'day',
        querySource: {
            kind: NodeKind.StickinessQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        },
        indexedResults: [trendResult],
        openPersonsModal: jest.fn(),
        ...overrides,
    }
}

describe('handleStickinessChartClick', () => {
    it('opens the persons modal with the legacy stickiness actors-query shape', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        handleStickinessChartClick(keyFor(trendResult), 1, deps)

        expect(openPersonsModal).toHaveBeenCalledTimes(1)
        const call = openPersonsModal.mock.calls[0][0]
        expect(call.query).toMatchObject({
            kind: NodeKind.InsightActorsQuery,
            day: 2,
            series: 0,
            includeRecordings: true,
        })
        // Stickiness must omit additionalSelect entries and orderBy — legacy parity
        // with ActionsLineGraph (isLifecycle || isStickiness branch).
        expect(call.additionalSelect).toEqual({})
        expect(call.orderBy).toBeUndefined()
    })

    it('renders a "stickiness on {interval} {day}" title with the series label', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult({ label: '$pageview' })
        const deps = makeDeps({ openPersonsModal, interval: 'day', indexedResults: [trendResult] })

        handleStickinessChartClick(keyFor(trendResult), 2, deps)

        const { container } = render(<>{openPersonsModal.mock.calls[0][0].title}</>)
        // PropertyKeyInfo wraps the raw label; the label text itself surfaces in textContent.
        expect(container.textContent).toContain('$pageview')
        expect(container.textContent).toContain('stickiness on day 3')
    })

    it('uses "day" as the default interval when interval is null', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({ openPersonsModal, interval: null, indexedResults: [trendResult] })

        handleStickinessChartClick(keyFor(trendResult), 0, deps)

        const { container } = render(<>{openPersonsModal.mock.calls[0][0].title}</>)
        expect(container.textContent).toContain('stickiness on day 1')
    })

    it.each([
        ['breakdown_value', { breakdown_value: 'Spike' }, 1, { day: 2, breakdown: 'Spike' }],
        ['compare_label', { compare_label: CompareLabelType.Previous }, 0, { day: 1, compare: 'previous' }],
    ] as const)('includes %s in the onDataPointClick payload when present', (_field, override, dataIndex, expected) => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const trendResult = makeTrendResult(override)
        const deps = makeDeps({
            openPersonsModal,
            indexedResults: [trendResult],
            context: { onDataPointClick },
        })

        handleStickinessChartClick(keyFor(trendResult), dataIndex, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
        expect(onDataPointClick).toHaveBeenCalledTimes(1)
        expect(onDataPointClick).toHaveBeenCalledWith(expect.objectContaining(expected), expect.anything())
    })

    it('passes indexedResults[0] (not the clicked dataset) as the second arg to onDataPointClick', () => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const firstResult = makeTrendResult({ id: 0, label: 'first' })
        const secondResult = makeTrendResult({ id: 1, label: 'second' })
        const deps = makeDeps({
            openPersonsModal,
            indexedResults: [firstResult, secondResult],
            context: { onDataPointClick },
        })

        handleStickinessChartClick(keyFor(secondResult), 1, deps)

        expect(onDataPointClick.mock.calls[0][1]).toBe(firstResult)
        expect(onDataPointClick.mock.calls[0][1]).not.toBe(secondResult)
    })

    it('does nothing when hasPersonsModal is false and no context callback', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({ openPersonsModal, hasPersonsModal: false, indexedResults: [trendResult] })

        handleStickinessChartClick(keyFor(trendResult), 1, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
    })

    it('still fires context.onDataPointClick when hasPersonsModal is false', () => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({
            openPersonsModal,
            hasPersonsModal: false,
            indexedResults: [trendResult],
            context: { onDataPointClick },
        })

        handleStickinessChartClick(keyFor(trendResult), 1, deps)

        expect(onDataPointClick).toHaveBeenCalledTimes(1)
        expect(openPersonsModal).not.toHaveBeenCalled()
    })

    it('no-ops when the clicked series has no matching indexedResult', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult({ id: 42 })
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        expect(() => handleStickinessChartClick('999', 1, deps)).not.toThrow()
        expect(openPersonsModal).not.toHaveBeenCalled()
    })

    it('uses trendResult.days[index] as fallback when action.days is missing', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult({
            action: { id: '$pageview', type: EntityTypes.EVENTS, order: 0, name: '$pageview' },
            days: daysAsType([10, 20, 30]),
        })
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        handleStickinessChartClick(keyFor(trendResult), 2, deps)

        expect(openPersonsModal.mock.calls[0][0].query).toMatchObject({ day: 30 })
    })

    it('no-ops when neither action.days nor trendResult.days can supply a day', () => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const trendResult = makeTrendResult({
            action: { id: '$pageview', type: EntityTypes.EVENTS, order: 0, name: '$pageview' },
            days: [],
        })
        const deps = makeDeps({
            openPersonsModal,
            indexedResults: [trendResult],
            context: { onDataPointClick },
        })

        handleStickinessChartClick(keyFor(trendResult), 2, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
        expect(onDataPointClick).not.toHaveBeenCalled()
    })

    it('does nothing when querySource is missing and no context callback', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({ openPersonsModal, querySource: null, indexedResults: [trendResult] })

        handleStickinessChartClick(keyFor(trendResult), 1, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
    })
})
