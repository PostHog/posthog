import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { findNegatedUnsetPropertyKeys } from './negatedPropertyFilters'

function group(values: UniversalFiltersGroup['values']): UniversalFiltersGroup {
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values }] }
}

describe('findNegatedUnsetPropertyKeys', () => {
    it.each([
        [
            'negated custom event property',
            [{ type: PropertyFilterType.Event, key: 'error_name', operator: PropertyOperator.IsNot, value: ['x'] }],
            ['error_name'],
        ],
        [
            'negated person property',
            [
                {
                    type: PropertyFilterType.Person,
                    key: 'plan',
                    operator: PropertyOperator.NotIContains,
                    value: ['free'],
                },
            ],
            ['plan'],
        ],
        [
            'engine-filled exception property is safe',
            [
                {
                    type: PropertyFilterType.Event,
                    key: '$exception_types',
                    operator: PropertyOperator.IsNot,
                    value: ['AxiosError'],
                },
            ],
            [],
        ],
        [
            'positive operator does not warn',
            [{ type: PropertyFilterType.Event, key: 'error_name', operator: PropertyOperator.Exact, value: ['x'] }],
            [],
        ],
        [
            'is_not_set does not warn',
            [{ type: PropertyFilterType.Event, key: 'error_name', operator: PropertyOperator.IsNotSet, value: null }],
            [],
        ],
    ])('%s', (_name, values, expected) => {
        expect(findNegatedUnsetPropertyKeys(group(values as UniversalFiltersGroup['values']))).toEqual(expected)
    })

    it('finds negated filters inside nested OR groups and de-duplicates keys', () => {
        const filterGroup: UniversalFiltersGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.Or,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: 'error_name',
                            operator: PropertyOperator.IsNot,
                            value: ['a'],
                        },
                        {
                            type: PropertyFilterType.Event,
                            key: 'error_name',
                            operator: PropertyOperator.NotRegex,
                            value: ['b'],
                        },
                    ],
                },
            ],
        }
        expect(findNegatedUnsetPropertyKeys(filterGroup)).toEqual(['error_name'])
    })
})
