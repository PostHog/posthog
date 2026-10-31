import { notificationsRailSignal } from './notificationsRailSignal'

describe('notificationsRailSignal', () => {
    it.each([
        ['nothing unread', { count: 0, direct_count: 0, has_critical: false }, 0, 'none'],
        ['items for the person', { count: 5, direct_count: 3, has_critical: false }, 3, 'notice'],
        ['team items only', { count: 2, direct_count: 0, has_critical: false }, 0, 'notice'],
        ['a critical team item', { count: 1, direct_count: 0, has_critical: true }, 0, 'critical'],
    ])('%s', (_name, summary, count, severity) => {
        expect(notificationsRailSignal(summary)).toMatchObject({ count, severity })
    })
})
