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
import type { NotificationApi, NotificationsListParams, PaginatedNotificationListApi } from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

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
): Promise<PaginatedNotificationListApi> => {
    return apiMutator<PaginatedNotificationListApi>(getNotificationsListUrl(projectId, params), {
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
    notificationApi: NonReadonly<NotificationApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotificationsMarkReadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notificationApi),
    })
}

export const getNotificationsMarkAllReadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/notifications/mark_all_read/`
}

export const notificationsMarkAllReadCreate = async (
    projectId: string,
    notificationApi: NonReadonly<NotificationApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotificationsMarkAllReadCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notificationApi),
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
