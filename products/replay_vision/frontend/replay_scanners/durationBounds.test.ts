import { PropertyFilterType, PropertyOperator, RecordingDurationFilter } from '~/types'

import { durationFilterError } from './durationBounds'

function durationFilter(
    key: 'duration' | 'active_seconds' | 'inactive_seconds',
    operator: PropertyOperator,
    value: number
): RecordingDurationFilter {
    return { type: PropertyFilterType.Recording, key, operator, value }
}

describe('durationBounds', () => {
    it.each([
        // A filter that can't overlap the scannable window [min, max] scans nothing → error.
        ['active time > ceiling', durationFilter('active_seconds', PropertyOperator.GreaterThan, 3600), true],
        ['active time > above ceiling', durationFilter('active_seconds', PropertyOperator.GreaterThan, 5000), true],
        ['active time < floor', durationFilter('active_seconds', PropertyOperator.LessThan, 10), true],
        // Filters that do overlap the window are fine.
        ['active time > small value', durationFilter('active_seconds', PropertyOperator.GreaterThan, 30), false],
        ['active time < large value', durationFilter('active_seconds', PropertyOperator.LessThan, 600), false],
        // `duration` has only a min bound, so a large `>` is not empty.
        ['total duration > large value', durationFilter('duration', PropertyOperator.GreaterThan, 99999), false],
        // Unbounded key and missing filter never error.
        ['unbounded key', durationFilter('inactive_seconds', PropertyOperator.GreaterThan, 99999), false],
        ['no filter', undefined, false],
    ])('flags an empty duration filter: %s', (_label, filter, expectError) => {
        expect(durationFilterError(filter)).toEqual(expectError ? expect.any(String) : null)
    })
})
