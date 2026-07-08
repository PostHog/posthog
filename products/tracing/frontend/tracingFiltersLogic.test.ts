import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { tracingFiltersLogic } from './tracingFiltersLogic'

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
