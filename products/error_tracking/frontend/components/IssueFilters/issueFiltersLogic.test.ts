import { expectLogic } from 'kea-test-utils'

import { quickFiltersLogic } from 'lib/components/QuickFilters'
import { quickFiltersSectionLogic } from 'lib/components/QuickFilters/quickFiltersSectionLogic'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    QuickFilter,
    UniversalFiltersGroup,
} from '~/types'

import { issueFiltersLogic } from './issueFiltersLogic'

const LOGIC_KEY = 'test'

const mockEnvFilter: QuickFilter = {
    id: 'filter-env',
    name: 'Environment',
    property_name: '$environment',
    type: 'manual-options',
    options: [{ id: 'opt-prod', value: 'production', label: 'Production', operator: PropertyOperator.Exact }],
    contexts: [QuickFilterContext.ErrorTrackingIssueFilters],
    created_at: '2024-01-01',
    updated_at: '2024-01-01',
}

describe('issueFiltersLogic', () => {
    let logic: ReturnType<typeof issueFiltersLogic.build>
    let quickFiltersSection: ReturnType<typeof quickFiltersSectionLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: [mockEnvFilter] },
            },
        })
        initKeaTests()
        logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()
        quickFiltersLogic({ context: QuickFilterContext.ErrorTrackingIssueFilters }).mount()
        quickFiltersSection = quickFiltersSectionLogic({
            context: QuickFilterContext.ErrorTrackingIssueFilters,
            logicKey: LOGIC_KEY,
        })
        quickFiltersSection.mount()
    })

    afterEach(() => {
        logic.unmount()
        quickFiltersSection.unmount()
    })

    describe('mergedFilterGroup', () => {
        const propA: EventPropertyFilter = {
            type: PropertyFilterType.Event,
            key: '$browser',
            operator: PropertyOperator.Exact,
            value: ['Chrome'],
        }
        const propB: EventPropertyFilter = {
            type: PropertyFilterType.Event,
            key: '$os',
            operator: PropertyOperator.Exact,
            value: ['Linux'],
        }

        it('preserves OR operator from filterGroup when no quick filters are selected', async () => {
            const filterGroup: UniversalFiltersGroup = {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.Or, values: [propA, propB] }],
            }

            await expectLogic(logic, () => {
                logic.actions.setFilterGroup(filterGroup)
            }).toFinishAllListeners()

            const merged = logic.values.mergedFilterGroup
            const inner = merged.values[0] as UniversalFiltersGroup
            expect(inner.type).toBe(FilterLogicalOperator.Or)
            expect(inner.values).toEqual([propA, propB])
        })

        it('preserves AND operator from filterGroup when no quick filters are selected', async () => {
            const filterGroup: UniversalFiltersGroup = {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [propA, propB] }],
            }

            await expectLogic(logic, () => {
                logic.actions.setFilterGroup(filterGroup)
            }).toFinishAllListeners()

            const merged = logic.values.mergedFilterGroup
            const inner = merged.values[0] as UniversalFiltersGroup
            expect(inner.type).toBe(FilterLogicalOperator.And)
            expect(inner.values).toEqual([propA, propB])
        })

        it('falls back to AND when filterGroup has no inner values', async () => {
            const merged = logic.values.mergedFilterGroup
            const inner = merged.values[0] as UniversalFiltersGroup
            expect(inner.type).toBe(FilterLogicalOperator.And)
            expect(inner.values).toEqual([])
        })

        it('nests OR omnisearch group when quick filters are also selected', async () => {
            const filterGroup: UniversalFiltersGroup = {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.Or, values: [propA, propB] }],
            }

            await expectLogic(logic, () => {
                logic.actions.setFilterGroup(filterGroup)
                quickFiltersSection.actions.setQuickFilterValue(
                    mockEnvFilter.id,
                    mockEnvFilter.property_name,
                    mockEnvFilter.options[0]
                )
            }).toFinishAllListeners()

            const merged = logic.values.mergedFilterGroup
            const inner = merged.values[0] as UniversalFiltersGroup
            // Outer-inner stays AND so the OR group AND's with the quick filter.
            expect(inner.type).toBe(FilterLogicalOperator.And)
            const nestedOr = inner.values[0] as UniversalFiltersGroup
            expect(nestedOr.type).toBe(FilterLogicalOperator.Or)
            expect(nestedOr.values).toEqual([propA, propB])
            expect(inner.values.slice(1)).toEqual([
                {
                    type: PropertyFilterType.Event,
                    key: mockEnvFilter.property_name,
                    operator: PropertyOperator.Exact,
                    value: ['production'],
                },
            ])
        })

        it('flattens AND omnisearch with quick filters into a single AND list', async () => {
            const filterGroup: UniversalFiltersGroup = {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [propA] }],
            }

            await expectLogic(logic, () => {
                logic.actions.setFilterGroup(filterGroup)
                quickFiltersSection.actions.setQuickFilterValue(
                    mockEnvFilter.id,
                    mockEnvFilter.property_name,
                    mockEnvFilter.options[0]
                )
            }).toFinishAllListeners()

            const merged = logic.values.mergedFilterGroup
            const inner = merged.values[0] as UniversalFiltersGroup
            expect(inner.type).toBe(FilterLogicalOperator.And)
            expect(inner.values).toEqual([
                propA,
                {
                    type: PropertyFilterType.Event,
                    key: mockEnvFilter.property_name,
                    operator: PropertyOperator.Exact,
                    value: ['production'],
                },
            ])
        })
    })
})
