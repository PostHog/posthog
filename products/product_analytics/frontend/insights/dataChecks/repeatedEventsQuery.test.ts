import { repeatedEventsQueryOf } from './repeatedEventsQuery'

describe('repeatedEventsQueryOf', () => {
    it.each<[string, string[], string]>([
        ['escapes a quote in an event name', ["it's done", '$pageview'], "event IN ('it\\'s done', '$pageview') AND "],
        ['reads every event when the check named none', [], 'WHERE timestamp >= now() - INTERVAL 3 DAY'],
    ])('%s', (_name, events, expected) => {
        expect(repeatedEventsQueryOf(events, 3)).toContain(expected)
    })
})
