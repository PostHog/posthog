import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type { NotificationsListParams, PaginatedNotificationEventListApi } from './api.schemas'

export const getNotificationsListUrl = (projectId: string, params?: NotificationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/notifications/?${stringifiedParams}`
        : `/api/environments/${projectId}/notifications/`
}

export const notificationsList = async (
    projectId: string,
    params?: NotificationsListParams,
    options?: RequestInit
): Promise<PaginatedNotificationEventListApi> => {
    return apiMutator<PaginatedNotificationEventListApi>(getNotificationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getNotificationsMarkReadCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/notifications/${id}/mark_read/`
}

export const notificationsMarkReadCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotificationsMarkReadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getNotificationsMarkUnreadCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/notifications/${id}/mark_unread/`
}

export const notificationsMarkUnreadCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotificationsMarkUnreadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getNotificationsMarkAllReadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/notifications/mark_all_read/`
}

export const notificationsMarkAllReadCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getNotificationsMarkAllReadCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getNotificationsUnreadCountRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/notifications/unread_count/`
}

export const notificationsUnreadCountRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getNotificationsUnreadCountRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
