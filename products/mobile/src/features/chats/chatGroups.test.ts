import type { ChatListItem } from '@/model/types'

import { dayLabel, filterChats, groupChats } from './chatGroups'

// Built from local components because labels follow the device's calendar days. Tuesday, Oct 13, 2026.
const now = new Date(2026, 9, 13, 18, 30)

function at(year: number, month: number, day: number, hours = 12): string {
    return new Date(year, month, day, hours).toISOString()
}

function item(id: string, title: string, updatedAt: string): ChatListItem {
    return {
        id: `session:${id}`,
        kind: 'session',
        sourceId: id,
        origin: 'session',
        title,
        updatedAt,
        status: 'idle',
        pullRequestUrl: null,
    }
}

describe('chat groups', () => {
    test.each([
        ['earlier today', at(2026, 9, 13, 0), 'Today'],
        ['yesterday', at(2026, 9, 12, 23), 'Yesterday'],
        ['3 days ago', at(2026, 9, 10), 'Saturday'],
        ['6 days ago', at(2026, 9, 7), 'Wednesday'],
        ['7 days ago', at(2026, 9, 6), 'Oct 6'],
        ['10 days ago', at(2026, 9, 3), 'Oct 3'],
        ['last year', at(2025, 9, 3), 'Oct 3, 2025'],
        ['a future time', at(2026, 9, 15), 'Today'],
        ['an invalid time', 'not a date', 'Earlier'],
    ])('labels %s as %s', (_case, iso, expected) => {
        expect(dayLabel(iso, now)).toBe(expected)
    })

    test('groups rows by day in first-seen order and keeps their order', () => {
        const items = [
            item('a', 'A', at(2026, 9, 13, 17)),
            item('b', 'B', at(2026, 9, 13, 9)),
            item('c', 'C', at(2026, 9, 12)),
            item('d', 'D', 'not a date'),
        ]
        expect(
            groupChats(items, now).map((group) => [group.label, group.items.map((entry) => entry.sourceId)])
        ).toEqual([
            ['Today', ['a', 'b']],
            ['Yesterday', ['c']],
            ['Earlier', ['d']],
        ])
    })

    test.each([
        ['', ['a', 'b']],
        ['   ', ['a', 'b']],
        ['  SIGNUP ', ['a']],
        ['checkout', ['b']],
        ['nothing', []],
    ])('filters by title for %j', (query, expected) => {
        const items = [
            item('a', 'Why did signups drop?', at(2026, 9, 13)),
            item('b', 'Checkout errors', at(2026, 9, 12)),
        ]
        expect(filterChats(items, query).map((entry) => entry.sourceId)).toEqual(expected)
    })
})
