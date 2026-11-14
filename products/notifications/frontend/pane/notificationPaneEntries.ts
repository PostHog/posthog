import { Dayjs, dayjs } from 'lib/dayjs'

import { buildNotificationSourcePath } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { shortTimeAgo } from '~/layout/today/todayWorkItems'

import { NotificationEventApi } from '../generated/api.schemas'
import { isPersonalNotification } from './notificationKinds'

export interface NotificationPaneEntry {
    key: string
    notification: NotificationEventApi
    children: NotificationEventApi[]
    count: number
    context: string
    projectName: string | null
    to: string | null
    timeText: string
    timeTitle: string
}

export interface NotificationPaneEntryOptions {
    projectNames: Record<number, string>
    now?: Dayjs
}

function paneGroupKey(notification: NotificationEventApi): string {
    if (isPersonalNotification(notification.notification_type) || !notification.resource_id) {
        return notification.id
    }
    return [
        notification.team_id ?? 'org',
        notification.notification_type,
        `${notification.resource_type ?? ''}:${notification.resource_id}`,
    ].join('|')
}

function sourcePath(notification: NotificationEventApi): string | null {
    return buildNotificationSourcePath({ ...notification, metadata: null })
}

function toEntry(
    group: NotificationEventApi[],
    key: string,
    { projectNames, now = dayjs() }: NotificationPaneEntryOptions
): NotificationPaneEntry {
    const [latest] = group
    const to = sourcePath(latest)
    return {
        key,
        notification: { ...latest, read: group.every((item) => item.read) },
        children: group,
        count: group.length,
        context: latest.body,
        projectName: latest.team_id !== null ? (projectNames[latest.team_id] ?? null) : null,
        to,
        timeText: shortTimeAgo(latest.created_at, now),
        timeTitle: dayjs(latest.created_at).format('LLL'),
    }
}

const CRITICAL_PRIORITY = 'critical'
const DIRECT_TARGET_TYPES: ReadonlySet<string> = new Set(['user', 'role'])

function groupedEntries(
    notifications: NotificationEventApi[],
    options: NotificationPaneEntryOptions
): NotificationPaneEntry[] {
    const groups = new Map<string, NotificationEventApi[]>()
    for (const notification of notifications) {
        const key = paneGroupKey(notification)
        const group = groups.get(key)
        if (group) {
            group.push(notification)
        } else {
            groups.set(key, [notification])
        }
    }
    return [...groups].map(([key, group]) => toEntry(group, key, options))
}

function isUnreadCritical({ notification }: NotificationPaneEntry): boolean {
    return !notification.read && notification.priority === CRITICAL_PRIORITY
}

/** An unread item sent to the person by name gets the full row with its next action. */
export function showsActionRow(entry: NotificationPaneEntry): boolean {
    return (
        !entry.notification.read && (isUnreadCritical(entry) || DIRECT_TARGET_TYPES.has(entry.notification.target_type))
    )
}

/** One list, newest first, with unread critical items pinned above everything else. */
export function buildInboxEntries(
    notifications: NotificationEventApi[],
    options: NotificationPaneEntryOptions
): NotificationPaneEntry[] {
    const entries = groupedEntries(notifications, options)
    return [...entries.filter(isUnreadCritical), ...entries.filter((entry) => !isUnreadCritical(entry))]
}
