import { dayjs } from 'lib/dayjs'

import { NotificationEventApi } from '../generated/api.schemas'
import { buildInboxEntries, showsActionRow } from './notificationPaneEntries'

const NOW = dayjs('2026-10-27T15:00:00Z')

function makeNotification(overrides: Partial<NotificationEventApi>): NotificationEventApi {
    return {
        id: 'n',
        team_id: 1,
        notification_type: 'pipeline_failure',
        priority: 'normal',
        title: 'Batch export failed',
        body: '',
        read: false,
        read_at: null,
        archived: false,
        target_type: 'team',
        target_id: '1',
        resource_type: 'batch_export',
        resource_id: 'be-1',
        source_url: '',
        source_type: null,
        source_id: null,
        metadata: null,
        created_at: NOW.toISOString(),
        ...overrides,
    }
}

describe('buildInboxEntries', () => {
    const build = (items: NotificationEventApi[]): ReturnType<typeof buildInboxEntries> =>
        buildInboxEntries(items, { projectNames: { 1: 'Web app' }, now: NOW })

    it('folds repeats on one object into one row across days', () => {
        const entries = build([
            makeNotification({ id: 'today' }),
            makeNotification({ id: 'four-days-ago', created_at: NOW.subtract(4, 'day').toISOString() }),
            makeNotification({ id: 'other-export', resource_id: 'be-2' }),
        ])

        expect(entries.map((entry) => [entry.notification.id, entry.count])).toEqual([
            ['today', 2],
            ['other-export', 1],
        ])
    })

    it('keeps every mention as its own row', () => {
        const mention = { notification_type: 'comment_mention', target_type: 'user', resource_type: 'insight' }
        const entries = build([makeNotification({ id: 'a', ...mention }), makeNotification({ id: 'b', ...mention })])

        expect(entries).toHaveLength(2)
    })

    it('pins unread critical items above newer ones', () => {
        const entries = build([
            makeNotification({ id: 'newer', resource_id: 'be-2' }),
            makeNotification({
                id: 'critical',
                priority: 'critical',
                created_at: NOW.subtract(3, 'hour').toISOString(),
            }),
        ])

        expect(entries.map((entry) => entry.notification.id)).toEqual(['critical', 'newer'])
    })

    it.each([
        ['an unread item sent to the person', { target_type: 'user' }, true],
        ['an unread item sent through a role', { target_type: 'role' }, true],
        ['an unread critical team item', { priority: 'critical' }, true],
        ['an unread team item', {}, false],
        ['a read item sent to the person', { target_type: 'user', read: true }, false],
    ])('shows the full row for %s: %s', (_name, overrides, expected) => {
        const [entry] = build([makeNotification(overrides)])

        expect(showsActionRow(entry)).toBe(expected)
    })
})
