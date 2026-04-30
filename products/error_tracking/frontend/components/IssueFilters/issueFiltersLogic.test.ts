import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { issueFiltersLogic } from './issueFiltersLogic'

describe('issueFiltersLogic', () => {
    let logic: ReturnType<typeof issueFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = issueFiltersLogic({ logicKey: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('mergedFilterGroup', () => {
        const propA = {
            type: PropertyFilterType.Event,
            key: '$browser',
            operator: PropertyOperator.Exact,
            value: ['Chrome'],
        }
        const propB = {
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
    })
})
