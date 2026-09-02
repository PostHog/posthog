import {
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { groupHasNoFilters } from './ScannerTriggers'

const leaf: EventPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$current_url',
    operator: PropertyOperator.IContains,
    value: 'checkout',
}

function group(...values: UniversalFiltersGroup['values']): UniversalFiltersGroup {
    return { type: FilterLogicalOperator.And, values }
}

describe('groupHasNoFilters', () => {
    it.each([
        // The shape recordingsQueryToUniversalFilters produces for a scanner with no filters: an outer group
        // wrapping one empty inner group, so a length check on the outer group would wrongly report a filter.
        ['outer group wrapping an empty inner group', group(group()), true],
        ['a group with no values at all', group(), true],
        ['empty groups nested several levels deep', group(group(group(group()))), true],
        ['outer group wrapping an inner group with a leaf', group(group(leaf)), false],
        ['a leaf directly on the outer group', group(leaf), false],
        ['one empty group alongside one holding a leaf', group(group(), group(leaf)), false],
    ])('%s', (_name, value, expected) => {
        expect(groupHasNoFilters(value as UniversalFiltersGroup)).toBe(expected)
    })
})
