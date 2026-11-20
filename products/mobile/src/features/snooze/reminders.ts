import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'

import { getNotificationPreferences, type NotificationPreferences } from '@/api/notificationPreferences'

export interface SnoozeReminder {
    reportId: string
    projectId: number
    title: string
    until: string
}

export const SNOOZE_REMINDER_BODY = 'Snoozed report is back'

let reminderGeneration = 0

export function snoozeRemindersEnabled(preferences: NotificationPreferences): boolean {
    return preferences.mobile_push_enabled && preferences.mobile_push_snooze_enabled
}

export async function cancelScheduledSnoozeReminders(isCurrent: () => boolean = () => true): Promise<void> {
    reminderGeneration += 1
    if (Platform.OS === 'web') {
        return
    }
    const scheduled = await Notifications.getAllScheduledNotificationsAsync()
    if (!isCurrent()) {
        return
    }
    await Promise.all(
        scheduled
            .filter((notification) => notification.content.data?.notificationKind === 'snooze_reminder')
            .map((notification) => Notifications.cancelScheduledNotificationAsync(notification.identifier))
    )
}

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
    const generation = reminderGeneration
    if (Platform.OS === 'web' || !isCurrent()) {
        return undefined
    }
    const preferences = await getNotificationPreferences()
    if (
        !snoozeRemindersEnabled(preferences) ||
        !(await mayNotify()) ||
        !isCurrent() ||
        generation !== reminderGeneration
    ) {
        return undefined
    }
    const identifier = await Notifications.scheduleNotificationAsync({
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
    if (!isCurrent() || generation !== reminderGeneration) {
        await Notifications.cancelScheduledNotificationAsync(identifier)
        return undefined
    }
    return identifier
}

export async function cancelSnoozeReminder(notificationId: string | undefined): Promise<void> {
    if (!notificationId || Platform.OS === 'web') {
        return
    }
    await Notifications.cancelScheduledNotificationAsync(notificationId)
}
