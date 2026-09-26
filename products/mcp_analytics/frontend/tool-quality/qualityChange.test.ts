import { errorRateChange, p95Change } from './qualityChange'

const row = (
    overrides: Partial<Parameters<typeof errorRateChange>[0]> = {}
): Parameters<typeof errorRateChange>[0] => ({
    total_calls: 100,
    previous_calls: 100,
    errors: 0,
    previous_errors: 0,
    p95_duration_ms: 500,
    previous_p95_duration_ms: 500,
    ...overrides,
})

describe('qualityChange', () => {
    it.each([
        ['below 20 calls in the current period', row({ total_calls: 19, errors: 10 }), null],
        ['below 20 calls in the previous period', row({ previous_calls: 19, errors: 30 }), null],
        [
            'a 5pp move that is still noise at 20 calls',
            row({ total_calls: 20, previous_calls: 20, errors: 3, previous_errors: 2 }),
            null,
        ],
        [
            'a 2pp move on 5,000 calls',
            row({ total_calls: 5000, previous_calls: 5000, errors: 250, previous_errors: 150 }),
            { worse: true, label: '2pp', previous: '3%' },
        ],
        ['a large drop', row({ errors: 5, previous_errors: 30 }), { worse: false, label: '25pp', previous: '30%' }],
        ['a flat rate', row({ errors: 10, previous_errors: 10 }), null],
    ])('error rate: %s', (_name, input, expected) => {
        expect(errorRateChange(input)).toEqual(expected)
    })

    it.each([
        ['exactly 25% slower', row({ p95_duration_ms: 625 }), { worse: true, label: '25%', previous: '500ms' }],
        ['24% slower', row({ p95_duration_ms: 620 }), null],
        ['exactly 20% faster', row({ p95_duration_ms: 400 }), { worse: false, label: '20%', previous: '500ms' }],
        ['no previous p95', row({ previous_p95_duration_ms: null }), null],
        ['no current timing data', row({ p95_duration_ms: 0 }), null],
        ['below 20 calls', row({ total_calls: 5, p95_duration_ms: 5000 }), null],
    ])('p95: %s', (_name, input, expected) => {
        expect(p95Change(input)).toEqual(expected)
    })
})
