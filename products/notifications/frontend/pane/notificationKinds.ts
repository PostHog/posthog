export type NotificationCategory = 'mentions' | 'approvals' | 'alerts' | 'pipelines' | 'other'

export const NOTIFICATION_CATEGORY_LABELS: Record<NotificationCategory, string> = {
    mentions: 'Mentions & assignments',
    approvals: 'Approvals',
    alerts: 'Alerts',
    pipelines: 'Data & pipelines',
    other: 'Other',
}

const CATEGORY_BY_TYPE: Record<string, NotificationCategory> = {
    comment_mention: 'mentions',
    issue_assigned: 'mentions',
    reminder: 'mentions',
    approval_requested: 'approvals',
    approval_resolved: 'approvals',
    alert_firing: 'alerts',
    usage_spike: 'alerts',
    email_reputation: 'alerts',
    pipeline_failure: 'pipelines',
    materialization_failure: 'pipelines',
    data_quality_check_failure: 'pipelines',
    feature_flag_failure: 'pipelines',
    experiment_concluded: 'other',
    web_analytics_digest: 'other',
    first_report_completed: 'other',
    project_created: 'other',
    achievement_unlocked: 'other',
    subscription_nudge: 'other',
    workflow_suggestion: 'other',
    notification_settings_changed: 'other',
}

const PERSONAL_CATEGORIES: ReadonlySet<NotificationCategory> = new Set(['mentions', 'approvals'])

export function notificationCategory(notificationType: string): NotificationCategory {
    return CATEGORY_BY_TYPE[notificationType] ?? 'other'
}

export function notificationTypesFor(category: NotificationCategory): string[] {
    return Object.entries(CATEGORY_BY_TYPE)
        .filter(([, typeCategory]) => typeCategory === category)
        .map(([notificationType]) => notificationType)
}

/** Mentions, assignments, reminders and approvals are about one person, so they show that person and never group. */
export function isPersonalNotification(notificationType: string): boolean {
    return PERSONAL_CATEGORIES.has(notificationCategory(notificationType))
}
