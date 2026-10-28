import { repeatedEventsQueryOf } from './repeatedEventsQuery'

const scope = { events: ['$pageview'], dateFrom: '2026-10-14', dateTo: '2026-10-20', sampleRate: 1 }

describe('repeatedEventsQueryOf', () => {
    it.each<[string, Partial<typeof scope>, string]>([
        ['escapes a quote in an event name', { events: ["it's done"] }, "event IN ['it\\'s done'] AND "],
        [
            'reads every event when the check named none',
            { events: [] },
            "WHERE toDate(timestamp) >= toDate('2026-10-14')",
        ],
        ['reads the share of people the check sampled', { sampleRate: 0.01234 }, 'FROM events SAMPLE 0.0123\n'],
        ['reads everyone when the check read every event', {}, 'FROM events\n'],
    ])('%s', (_name, change, expected) => {
        expect(repeatedEventsQueryOf({ ...scope, ...change })).toContain(expected)
    })
})
