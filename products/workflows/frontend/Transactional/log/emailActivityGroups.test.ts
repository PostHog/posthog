import { ActivityEvent, ActivityRow, buildActivityTimeline } from './emailActivity'
import { collapseGroup, groupActivityRows, groupDuration } from './emailActivityGroups'

function event(uuid: string, timestamp: string, sessionId: string | null, name = '$pageview'): ActivityEvent {
    return {
        uuid,
        event: name,
        timestamp,
        url: null,
        pathname: name === '$pageview' ? `/${uuid}` : null,
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
            name: 'does not fold a much later event with no session into the session',
            events: [
                event('a', '2026-06-15T09:00:00Z', 's1'),
                event('sync-1', '2026-06-15T09:01:00Z', null, 'synced'),
                event('sync-2', '2026-06-15T12:00:00Z', null, 'synced'),
            ],
            expected: [
                ['s1', ['a', 'sync-1']],
                [null, ['sync-2']],
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

    it('collapses a long group to its custom events once each, and counts what it leaves out', () => {
        const events = [
            event('a', '2026-06-15T09:00:00Z', 's1'),
            event('sync-1', '2026-06-15T09:00:10Z', 's1', 'synced'),
            event('b', '2026-06-15T09:00:20Z', 's1'),
            event('paid', '2026-06-15T09:00:30Z', 's1', 'paid'),
            event('c', '2026-06-15T09:00:40Z', 's1'),
            event('sync-2', '2026-06-15T09:00:50Z', 's1', 'synced'),
        ]
        const { rows: shown, hidden } = collapseGroup(groupActivityRows(rows(events))[0])
        expect(shown.map((row) => (row.kind === 'event' ? [row.event.event, row.count] : null))).toEqual([
            ['synced', 2],
            ['paid', 1],
        ])
        expect(hidden).toBe(4)
    })

    it('shows the first rows of a long group with no custom events', () => {
        const events = ['a', 'b', 'c', 'd', 'e', 'f'].map((id, i) => event(id, `2026-06-15T09:00:0${i}Z`, 's1'))
        const { rows: shown, hidden } = collapseGroup(groupActivityRows(rows(events))[0])
        expect(shown.map((row) => row.key)).toEqual(['a', 'b', 'c', 'd'])
        expect(hidden).toBe(2)
    })

    it('ends a session at the last of its folded events', () => {
        const [group] = groupActivityRows(
            rows([
                event('a', '2026-06-15T09:00:00Z', 's1', 'opened'),
                event('b', '2026-06-15T09:20:00Z', 's1', 'opened'),
            ])
        )
        expect(groupDuration(group)).toBe('20m')
    })
})
