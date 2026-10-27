import { NotificationEventApi, NotificationsListParams } from '../generated/api.schemas'
import { NotificationCategory, notificationCategory, notificationTypesFor } from './notificationKinds'

export type NotificationsReadFilter = 'all' | 'unread'
export type NotificationsCategoryFilter = 'any' | NotificationCategory
export type NotificationsProjectFilter = 'all' | 'current'

export interface NotificationsPaneFilters {
    read: NotificationsReadFilter
    category: NotificationsCategoryFilter
    project: NotificationsProjectFilter
}

export const DEFAULT_NOTIFICATIONS_PANE_FILTERS: NotificationsPaneFilters = {
    read: 'all',
    category: 'any',
    project: 'all',
}

export function notificationsPaneFiltersActive(filters: NotificationsPaneFilters): boolean {
    return (Object.keys(filters) as (keyof NotificationsPaneFilters)[]).some(
        (key) => filters[key] !== DEFAULT_NOTIFICATIONS_PANE_FILTERS[key]
    )
}

export type NotificationsFilterQuery = Pick<NotificationsListParams, 'read' | 'notification_type' | 'team_id'>

export function filtersToQuery(
    filters: NotificationsPaneFilters,
    currentTeamId: number | null
): NotificationsFilterQuery {
    return {
        read: filters.read === 'unread' ? false : undefined,
        notification_type: filters.category === 'any' ? undefined : notificationTypesFor(filters.category).join(','),
        team_id: filters.project === 'current' && currentTeamId !== null ? currentTeamId : undefined,
    }
}

/** Whether a notification pushed live belongs in the list the person is looking at. */
export function matchesFilters(
    notification: NotificationEventApi,
    filters: NotificationsPaneFilters,
    currentTeamId: number | null
): boolean {
    if (filters.read === 'unread' && notification.read) {
        return false
    }
    if (filters.category !== 'any' && notificationCategory(notification.notification_type) !== filters.category) {
        return false
    }
    return filters.project === 'all' || notification.team_id === null || notification.team_id === currentTeamId
}
