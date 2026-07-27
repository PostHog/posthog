import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { DEFAULT_CUSTOM_COMPARISON, tracingFiltersLogic } from './tracingFiltersLogic'

const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS
// Absolute range so window math is deterministic (relative ranges resolve against Date.now()).
const RANGE_START = Date.parse('2024-01-08T00:00:00Z')
const RANGE_END = RANGE_START + 4 * HOUR_MS
const ABSOLUTE_RANGE = { date_from: '2024-01-08T00:00:00Z', date_to: '2024-01-08T04:00:00Z' }

const PINNED_FILTERS: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            key: 'posthogDistinctId',
            type: PropertyFilterType.SpanAttribute,
            operator: PropertyOperator.Exact,
            value: ['distinct-id-1'],
        },
    ],
}

describe('tracingFiltersLogic', () => {
    let logic: ReturnType<typeof tracingFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = tracingFiltersLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('view mode', () => {
        it('defaults to traces', () => {
            expect(logic.values.viewMode).toBe('traces')
            expect(logic.values.filters.viewMode).toBe('traces')
        })

        it('switches to spans', () => {
            logic.actions.setViewMode('spans')
            expect(logic.values.viewMode).toBe('spans')
            expect(logic.values.filters.viewMode).toBe('spans')
        })

        it('switches back to traces', () => {
            logic.actions.setViewMode('spans')
            logic.actions.setViewMode('traces')
            expect(logic.values.viewMode).toBe('traces')
        })
    })

    describe('comparison windows', () => {
        beforeEach(() => {
            logic.actions.setDateRange(ABSOLUTE_RANGE)
        })

        it('covers the full selected range when no comparison is active (feeds the Operations aggregate)', () => {
            expect(logic.values.comparison).toBeNull()
            expect(logic.values.currentWindowMs).toEqual({ startMs: RANGE_START, endMs: RANGE_END })
        })

        test.each([
            ['previous_period', 4 * HOUR_MS],
            ['yesterday', DAY_MS],
            ['last_week', 7 * DAY_MS],
        ] as const)('%s compares the full range against the range shifted back', (preset, shiftMs) => {
            logic.actions.setComparison({ ...DEFAULT_CUSTOM_COMPARISON, preset })
            expect(logic.values.currentWindowMs).toEqual({ startMs: RANGE_START, endMs: RANGE_END })
            expect(logic.values.previousWindowMs).toEqual({
                startMs: RANGE_START - shiftMs,
                endMs: RANGE_END - shiftMs,
            })
        })

        it('custom preset defaults to the right-aligned 40% window and the -50%-shifted baseline', () => {
            logic.actions.setComparison(DEFAULT_CUSTOM_COMPARISON)
            const windowMs = 0.4 * 4 * HOUR_MS
            expect(logic.values.currentWindowMs).toEqual({ startMs: RANGE_END - windowMs, endMs: RANGE_END })
            const previousEnd = RANGE_END - 0.5 * 4 * HOUR_MS
            expect(logic.values.previousWindowMs).toEqual({ startMs: previousEnd - windowMs, endMs: previousEnd })
        })

        it('dragged custom windows override the defaults until the date range changes', () => {
            logic.actions.setComparison(DEFAULT_CUSTOM_COMPARISON)
            const current = { startMs: RANGE_START + HOUR_MS, endMs: RANGE_START + 2 * HOUR_MS }
            const previous = { startMs: RANGE_START, endMs: RANGE_START + HOUR_MS }
            logic.actions.updateComparisonWindows(current, previous)
            expect(logic.values.currentWindowMs).toEqual(current)
            expect(logic.values.previousWindowMs).toEqual(previous)

            // A new range invalidates the absolute-ms overrides but keeps the comparison active.
            logic.actions.setDateRange({ date_from: '2024-01-09T00:00:00Z', date_to: '2024-01-09T04:00:00Z' })
            expect(logic.values.comparison).toEqual(DEFAULT_CUSTOM_COMPARISON)
            expect(logic.values.currentWindowMs.endMs).toBe(RANGE_END + DAY_MS)
        })
    })

    describe('keyed instances', () => {
        it('holds independent state per id', () => {
            const a = tracingFiltersLogic({ id: 'instance-a' })
            const b = tracingFiltersLogic({ id: 'instance-b' })
            a.mount()
            b.mount()
            try {
                a.actions.setViewMode('spans')
                a.actions.setServiceNames(['svc-a'])

                expect(a.values.viewMode).toBe('spans')
                expect(a.values.filters.serviceNames).toEqual(['svc-a'])
                expect(b.values.viewMode).toBe('traces')
                expect(b.values.filters.serviceNames).toEqual([])
            } finally {
                a.unmount()
                b.unmount()
            }
        })

        it('merges pinned filters into queryFilterGroup without exposing them to editable state', () => {
            const pinned = tracingFiltersLogic({ id: 'pinned-instance', pinnedFilters: PINNED_FILTERS })
            pinned.mount()
            try {
                // The editable filterGroup (what the filter chips render) must not contain the
                // pinned filters — users must not be able to remove the embedder's scope.
                expect(JSON.stringify(pinned.values.filterGroup)).not.toContain('posthogDistinctId')

                // The query-facing group starts with the pinned filters...
                const inner = pinned.values.queryFilterGroup.values[0] as UniversalFiltersGroup
                expect(inner.values[0]).toMatchObject({ key: 'posthogDistinctId', value: ['distinct-id-1'] })

                // ...and keeps them when the user adds their own filter.
                pinned.actions.setFilterGroup({
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: 'http.method',
                                    type: PropertyFilterType.SpanAttribute,
                                    operator: PropertyOperator.Exact,
                                    value: ['GET'],
                                },
                            ],
                        },
                    ],
                })
                const combined = pinned.values.queryFilterGroup.values[0] as UniversalFiltersGroup
                expect(combined.values).toHaveLength(2)
                expect(combined.values[0]).toMatchObject({ key: 'posthogDistinctId' })
                expect(combined.values[1]).toMatchObject({ key: 'http.method' })
            } finally {
                pinned.unmount()
            }
        })
    })
})
