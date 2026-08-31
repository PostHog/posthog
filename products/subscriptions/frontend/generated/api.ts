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
    OutcomeDecisionApi,
    OutcomeDecisionDTOApi,
    PaginatedSubscriptionDeliveryListApi,
    PaginatedSubscriptionListApi,
    PatchedSubscriptionWriteApi,
    ProactiveConfigurationOptionsApi,
    PulseExperimentDraftApi,
    PulseExperimentDraftResponseApi,
    PulseOutcomeReplayResponseApi,
    PulseRunHistoryDTOApi,
    SubscriptionApi,
    SubscriptionDeliveryApi,
    SubscriptionWriteApi,
    SubscriptionsDeliveriesListParams,
    SubscriptionsListParams,
    SubscriptionsPulseHistoryListParams,
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
    subscriptionWriteApi: NonReadonly<SubscriptionWriteApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionWriteApi),
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
    subscriptionWriteApi: NonReadonly<SubscriptionWriteApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionWriteApi),
    })
}

export const getSubscriptionsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedSubscriptionWriteApi?: NonReadonly<PatchedSubscriptionWriteApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSubscriptionWriteApi),
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

export const getSubscriptionsPulseActionsDecisionCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/subscriptions/pulse/actions/${id}/decision/`
}

/**
 * Record an explicit adoption or dismissal for one advice-only proactive recommendation.
 */
export const subscriptionsPulseActionsDecisionCreate = async (
    projectId: string,
    id: string,
    outcomeDecisionApi: OutcomeDecisionApi,
    options?: RequestInit
): Promise<OutcomeDecisionDTOApi> => {
    return apiMutator<OutcomeDecisionDTOApi>(getSubscriptionsPulseActionsDecisionCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(outcomeDecisionApi),
    })
}

export const getSubscriptionsPulseConfigurationOptionsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/subscriptions/pulse/configuration-options/`
}

/**
 * Return the current user's safe proactive subscription configuration options. Repository options are limited to repositories the user can currently authorize.
 */
export const subscriptionsPulseConfigurationOptionsList = async (
    projectId: string,
    options?: RequestInit
): Promise<ProactiveConfigurationOptionsApi> => {
    return apiMutator<ProactiveConfigurationOptionsApi>(getSubscriptionsPulseConfigurationOptionsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getSubscriptionsPulseExperimentDraftsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/subscriptions/pulse/experiment-drafts/`
}

/**
 * Create the one inert experiment draft reserved for this staged Pulse task.
 */
export const subscriptionsPulseExperimentDraftsCreate = async (
    projectId: string,
    pulseExperimentDraftApi: PulseExperimentDraftApi,
    options?: RequestInit
): Promise<PulseExperimentDraftResponseApi> => {
    return apiMutator<PulseExperimentDraftResponseApi>(getSubscriptionsPulseExperimentDraftsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(pulseExperimentDraftApi),
    })
}

export const getSubscriptionsPulseHistoryListUrl = (projectId: string, params: SubscriptionsPulseHistoryListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/subscriptions/pulse/history/?${stringifiedParams}`
        : `/api/projects/${projectId}/subscriptions/pulse/history/`
}

/**
 * Return bounded proactive delivery history without raw evidence bodies.
 */
export const subscriptionsPulseHistoryList = async (
    projectId: string,
    params: SubscriptionsPulseHistoryListParams,
    options?: RequestInit
): Promise<PulseRunHistoryDTOApi[]> => {
    return apiMutator<PulseRunHistoryDTOApi[]>(getSubscriptionsPulseHistoryListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSubscriptionsPulseOutcomeReplaysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/subscriptions/pulse/outcome-replays/${id}/`
}

/**
 * Return the one server-derived comparison call for a claimed Pulse outcome. The instruction is available only to its active task-bound analysis sandbox.
 */
export const subscriptionsPulseOutcomeReplaysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PulseOutcomeReplayResponseApi> => {
    return apiMutator<PulseOutcomeReplayResponseApi>(getSubscriptionsPulseOutcomeReplaysRetrieveUrl(projectId, id), {
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
