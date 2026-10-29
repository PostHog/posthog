import * as Notifications from 'expo-notifications'

import { scheduleSnoozeReminder } from './reminders'

jest.mock('expo-notifications', () => ({
    getPermissionsAsync: jest.fn(async () => ({ granted: true })),
    scheduleNotificationAsync: jest.fn(async () => 'reminder-1'),
    SchedulableTriggerInputTypes: { DATE: 'date' },
}))

test('schedules an explicit snooze reminder with report routing and a distinct notification kind', async () => {
    await expect(
        scheduleSnoozeReminder({
            reportId: 'report-1',
            projectId: 2,
            title: 'Example report',
            until: '2030-01-01T00:00:00Z',
        })
    ).resolves.toBe('reminder-1')
    expect(Notifications.scheduleNotificationAsync).toHaveBeenCalledWith(
        expect.objectContaining({
            content: expect.objectContaining({
                data: {
                    type: 'report',
                    report_id: 'report-1',
                    project_id: 2,
                    notificationKind: 'snooze_reminder',
                },
            }),
        })
    )
})
