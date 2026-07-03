import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { filtersContainValues, ruleSaveErrorMessage } from './ruleModalUtils'

describe('ruleModalUtils', () => {
    const group = (values: UniversalFiltersGroup['values']): UniversalFiltersGroup => ({
        type: FilterLogicalOperator.And,
        values,
    })
    const withKey = {
        key: '$browser',
        value: ['Firefox'],
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    } as any
    const emptyRow = { type: PropertyFilterType.Event } as any

    // Guards the frontend/backend alignment: the server's `has_filter_values` gate drops keyless rows
    // and 400s, so Save must stay disabled until a real key is present (not merely a row).
    it.each([
        ['no rows', group([]), false],
        ['a row without a key', group([emptyRow]), false],
        ['a row with a key', group([withKey]), true],
        ['a keyless row alongside a real one', group([emptyRow, withKey]), true],
        ['a nested group with a key', group([group([withKey])]), true],
        ['a nested group without a key', group([group([emptyRow])]), false],
    ])('filtersContainValues is %s → %s', (_name, filters, expected) => {
        expect(filtersContainValues(filters)).toBe(expected)
    })

    it.each([
        [
            'prefers DRF detail',
            { detail: 'Filters must contain at least one filter value.' } as unknown,
            'Filters must contain at least one filter value.',
        ],
        ['falls back to message', { message: 'Network error' } as unknown, 'Network error'],
        ['accepts a bare string', 'Bad Request' as unknown, 'Bad Request'],
        [
            'generic fallback for unknown shapes',
            null as unknown,
            'Something went wrong saving this rule. Please try again.',
        ],
    ])('ruleSaveErrorMessage %s', (_name, error, expected) => {
        expect(ruleSaveErrorMessage(error)).toBe(expected)
    })
})
