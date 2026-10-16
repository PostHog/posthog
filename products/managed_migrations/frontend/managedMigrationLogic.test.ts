import { trialDistinctIdWarning } from './managedMigrationLogic'
import type { TrialSummary } from './types'

function summary(overrides: Partial<TrialSummary>): TrialSummary {
    return {
        source_records: 0,
        output_events: 0,
        dropped_records: 0,
        skipped_records: 0,
        event_name_counts: {},
        error_counts: {},
        ...overrides,
    }
}

describe('trialDistinctIdWarning', () => {
    test.each([
        ['no summary', null, null],
        ['spread out ids', summary({ output_events: 1000, distinct_id_counts: { a: 50, b: 40 } }), null],
        ['small trial with one heavy id', summary({ output_events: 20, distinct_id_counts: { a: 20 } }), null],
        [
            'one id holds a large share',
            summary({ output_events: 1000, distinct_id_counts: { a: 10, member_x: 300 } }),
            { topDistinctId: 'member_x', topDistinctIdShare: 0.3, placeholderEvents: 0 },
        ],
        [
            'placeholder ids in a small trial',
            summary({ output_events: 20, distinct_id_counts: { a: 15 }, placeholder_distinct_id_events: 5 }),
            { topDistinctId: null, topDistinctIdShare: 0.75, placeholderEvents: 5 },
        ],
    ])('%s', (_, input, expected) => {
        expect(trialDistinctIdWarning(input)).toEqual(expected)
    })
})
