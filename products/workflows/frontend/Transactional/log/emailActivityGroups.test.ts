import { ActivityEvent, ActivityRow, buildActivityTimeline } from './emailActivity'
import { groupActivityRows } from './emailActivityGroups'

function event(uuid: string, timestamp: string, sessionId: string | null, name = '$pageview'): ActivityEvent {
    return {
        uuid,
        event: name,
        timestamp,
        url: null,
        pathname: `/${uuid}`,
        sessionId,
        eventType: null,
        elementsChain: '',
    }
}

function rows(events: ActivityEvent[]): ActivityRow[] {
    return buildActivityTimeline(events, [], '2026-06-15T08:00:00Z').after
}

describe('emailActivityGroups', () => {
    it.each([
        {
            name: 'starts a new group for each session',
            events: [
                event('a', '2026-06-15T09:00:00Z', 's1'),
                event('b', '2026-06-15T09:01:00Z', 's1'),
                event('c', '2026-06-15T10:00:00Z', 's2'),
            ],
            expected: [
                ['s1', ['a', 'b']],
                ['s2', ['c']],
            ],
        },
        {
            name: 'keeps a server-side event inside the session it happened in',
            events: [
                event('a', '2026-06-15T09:00:00Z', 's1'),
                event('paid', '2026-06-15T09:01:00Z', null, 'invoice_paid'),
                event('b', '2026-06-15T09:02:00Z', 's1'),
            ],
            expected: [['s1', ['a', 'paid', 'b']]],
        },
        {
            name: 'splits off an event with no session once the session has gone quiet',
            events: [event('a', '2026-06-15T09:00:00Z', 's1'), event('later', '2026-06-15T12:00:00Z', null)],
            expected: [
                ['s1', ['a']],
                [null, ['later']],
            ],
        },
        {
            name: 'starts a session group after events with no session',
            events: [event('first', '2026-06-15T09:00:00Z', null), event('a', '2026-06-15T09:01:00Z', 's1')],
            expected: [
                [null, ['first']],
                ['s1', ['a']],
            ],
        },
    ])('$name', ({ events, expected }) => {
        const groups = groupActivityRows(rows(events))
        expect(groups.map((group) => [group.sessionId, group.rows.map((row) => row.key)])).toEqual(expected)
    })
})
