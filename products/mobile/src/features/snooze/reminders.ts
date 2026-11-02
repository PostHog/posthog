import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'

export interface SnoozeReminder {
    reportId: string
    projectId: number
    title: string
    until: string
}

export const SNOOZE_REMINDER_BODY = 'Snoozed report is back'

// Never asks for permission: after the first prompt at sign in, only the Settings button asks.
async function mayNotify(): Promise<boolean> {
    const current = await Notifications.getPermissionsAsync()
    return current.granted || current.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL
}

/** Undefined when notifications are off. The snooze itself still applies. */
export async function scheduleSnoozeReminder(
    reminder: SnoozeReminder,
    isCurrent: () => boolean = () => true
): Promise<string | undefined> {
    if (Platform.OS === 'web' || !(await mayNotify()) || !isCurrent()) {
        return undefined
    }
    return Notifications.scheduleNotificationAsync({
        content: {
            title: reminder.title,
            body: SNOOZE_REMINDER_BODY,
            // Same shape as the server's report pushes, so one tap handler routes both.
            data: {
                type: 'report',
                report_id: reminder.reportId,
                project_id: reminder.projectId,
                notificationKind: 'snooze_reminder',
            },
        },
        trigger: { type: Notifications.SchedulableTriggerInputTypes.DATE, date: new Date(reminder.until) },
    })
}

export async function cancelSnoozeReminder(notificationId: string | undefined): Promise<void> {
    if (!notificationId || Platform.OS === 'web') {
        return
    }
    await Notifications.cancelScheduledNotificationAsync(notificationId)
}
