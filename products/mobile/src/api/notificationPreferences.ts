import { apiJson } from './client'

export const DEFAULT_NOTIFICATION_PREFERENCES = {
    mobile_push_enabled: true,
    mobile_push_tasks_enabled: true,
    mobile_push_reports_enabled: true,
    mobile_push_report_updates_enabled: true,
    mobile_push_chat_enabled: true,
    mobile_push_loops_enabled: true,
    mobile_push_chat_attention_enabled: true,
    mobile_push_chat_mentions_enabled: true,
    mobile_push_chat_replies_enabled: true,
    mobile_push_chat_completions_enabled: true,
    mobile_push_chat_pr_outcomes_enabled: true,
    mobile_push_report_attention_enabled: true,
    mobile_push_report_completions_enabled: true,
    mobile_push_report_pr_ready_enabled: true,
    mobile_push_report_pr_outcomes_enabled: true,
    mobile_push_snooze_enabled: true,
}

export type NotificationPreferences = typeof DEFAULT_NOTIFICATION_PREFERENCES
export type NotificationPreferenceKey = keyof NotificationPreferences

interface UserNotificationSettings {
    notification_settings?: Partial<NotificationPreferences>
}

export async function getNotificationPreferences(signal?: AbortSignal): Promise<NotificationPreferences> {
    const user = await apiJson<UserNotificationSettings>('/api/users/@me/', { signal })
    return {
        ...DEFAULT_NOTIFICATION_PREFERENCES,
        mobile_push_chat_enabled: user.notification_settings?.mobile_push_tasks_enabled ?? true,
        mobile_push_loops_enabled: user.notification_settings?.mobile_push_tasks_enabled ?? true,
        ...user.notification_settings,
    }
}

export async function setNotificationPreference(
    key: NotificationPreferenceKey,
    enabled: boolean
): Promise<NotificationPreferences> {
    const user = await apiJson<UserNotificationSettings>('/api/users/@me/', {
        method: 'PATCH',
        json: { notification_settings: { [key]: enabled } },
    })
    return {
        ...DEFAULT_NOTIFICATION_PREFERENCES,
        mobile_push_chat_enabled: user.notification_settings?.mobile_push_tasks_enabled ?? true,
        mobile_push_loops_enabled: user.notification_settings?.mobile_push_tasks_enabled ?? true,
        ...user.notification_settings,
    }
}
