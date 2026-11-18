import * as Notifications from 'expo-notifications'
import { apiJson } from '@/api/client'
import { cancelScheduledSnoozeReminders, scheduleSnoozeReminder } from './reminders'

jest.mock('@/api/client', () => ({ apiJson: jest.fn() }))
jest.mock('expo-notifications', () => ({
    getPermissionsAsync: jest.fn(async () => ({ granted: true })),
    scheduleNotificationAsync: jest.fn(async () => 'reminder-1'),
    getAllScheduledNotificationsAsync: jest.fn(async () => []),
    cancelScheduledNotificationAsync: jest.fn(async () => undefined),
    SchedulableTriggerInputTypes: { DATE: 'date' },
}))
const reminder = { reportId: 'report-1', projectId: 2, title: 'Example report', until: '2030-01-01T00:00:00Z' }

describe('snooze reminders', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(apiJson).mockResolvedValue({ notification_settings: {} })
    })
    test('schedules a reminder with report routing and a distinct notification kind', async () => {
        await expect(scheduleSnoozeReminder(reminder)).resolves.toBe('reminder-1')
        expect(Notifications.scheduleNotificationAsync).toHaveBeenCalledWith(
            expect.objectContaining({
                content: expect.objectContaining({
                    data: { type: 'report', report_id: 'report-1', project_id: 2, notificationKind: 'snooze_reminder' },
                }),
            })
        )
    })
    test.each(['mobile_push_enabled', 'mobile_push_snooze_enabled'])(
        'does not schedule when %s is disabled',
        async (key) => {
            jest.mocked(apiJson).mockResolvedValue({ notification_settings: { [key]: false } })
            await expect(scheduleSnoozeReminder(reminder)).resolves.toBeUndefined()
            expect(Notifications.scheduleNotificationAsync).not.toHaveBeenCalled()
        }
    )
    test('cancels only snooze reminders, including one that finishes scheduling after cancellation', async () => {
        let finish!: (id: string) => void
        let started!: () => void
        const scheduling = new Promise<void>((resolve) => {
            started = resolve
        })
        jest.mocked(Notifications.scheduleNotificationAsync).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finish = resolve
                    started()
                })
        )
        const pending = scheduleSnoozeReminder(reminder)
        await scheduling
        jest.mocked(Notifications.getAllScheduledNotificationsAsync).mockResolvedValueOnce([
            {
                identifier: 'existing-snooze',
                trigger: null,
                content: {
                    title: null,
                    subtitle: null,
                    body: null,
                    categoryIdentifier: null,
                    sound: null,
                    threadIdentifier: null,
                    data: { notificationKind: 'snooze_reminder' },
                },
            },
            {
                identifier: 'unrelated',
                trigger: null,
                content: {
                    title: null,
                    subtitle: null,
                    body: null,
                    categoryIdentifier: null,
                    sound: null,
                    threadIdentifier: null,
                    data: { notificationKind: 'other' },
                },
            },
        ])
        await cancelScheduledSnoozeReminders()
        finish('in-flight-snooze')
        await expect(pending).resolves.toBeUndefined()
        expect(jest.mocked(Notifications.cancelScheduledNotificationAsync).mock.calls).toEqual([
            ['existing-snooze'],
            ['in-flight-snooze'],
        ])
    })
})
