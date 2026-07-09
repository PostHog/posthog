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
import type {
    PaginatedSubscriptionDeliveryListApi,
    PaginatedSubscriptionListApi,
    PatchedSubscriptionApi,
    SubscriptionApi,
    SubscriptionDeliveryApi,
    SubscriptionsDeliveriesListParams,
    SubscriptionsListParams,
    SubscriptionsSummaryQuotaRetrieve200,
} from './api.schemas'

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

export const getSubscriptionsListUrl = (projectId: string, params?: SubscriptionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/subscriptions/?${stringifiedParams}`
        : `/api/projects/${projectId}/subscriptions/`
}

export const subscriptionsList = async (
    projectId: string,
    params?: SubscriptionsListParams,
    options?: RequestInit
): Promise<PaginatedSubscriptionListApi> => {
    return apiMutator<PaginatedSubscriptionListApi>(getSubscriptionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSubscriptionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/subscriptions/`
}

export const subscriptionsCreate = async (
    projectId: string,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export const getSubscriptionsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSubscriptionsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsUpdate = async (
    projectId: string,
    id: number,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export const getSubscriptionsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedSubscriptionApi?: NonReadonly<PatchedSubscriptionApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSubscriptionApi),
    })
}

export const getSubscriptionsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const subscriptionsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getSubscriptionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getSubscriptionsTestDeliveryCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/test-delivery/`
}

export const subscriptionsTestDeliveryCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSubscriptionsTestDeliveryCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getSubscriptionsDeliveriesListUrl = (
    projectId: string,
    subscriptionId: number,
    params?: SubscriptionsDeliveriesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/subscriptions/${subscriptionId}/deliveries/?${stringifiedParams}`
        : `/api/projects/${projectId}/subscriptions/${subscriptionId}/deliveries/`
}

/**
 * Paginated delivery history for a subscription. Requires premium subscriptions.
 * @summary List subscription deliveries
 */
export const subscriptionsDeliveriesList = async (
    projectId: string,
    subscriptionId: number,
    params?: SubscriptionsDeliveriesListParams,
    options?: RequestInit
): Promise<PaginatedSubscriptionDeliveryListApi> => {
    return apiMutator<PaginatedSubscriptionDeliveryListApi>(
        getSubscriptionsDeliveriesListUrl(projectId, subscriptionId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getSubscriptionsDeliveriesRetrieveUrl = (projectId: string, subscriptionId: number, id: string) => {
    return `/api/projects/${projectId}/subscriptions/${subscriptionId}/deliveries/${id}/`
}

/**
 * Fetch one delivery row by id.
 * @summary Retrieve subscription delivery
 */
export const subscriptionsDeliveriesRetrieve = async (
    projectId: string,
    subscriptionId: number,
    id: string,
    options?: RequestInit
): Promise<SubscriptionDeliveryApi> => {
    return apiMutator<SubscriptionDeliveryApi>(getSubscriptionsDeliveriesRetrieveUrl(projectId, subscriptionId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSubscriptionsSummaryQuotaRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/subscriptions/summary_quota/`
}

export const subscriptionsSummaryQuotaRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<SubscriptionsSummaryQuotaRetrieve200> => {
    return apiMutator<SubscriptionsSummaryQuotaRetrieve200>(getSubscriptionsSummaryQuotaRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
