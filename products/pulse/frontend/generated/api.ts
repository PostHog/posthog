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
    PaginatedPulseDigestListListApi,
    PaginatedPulseFindingListApi,
    PaginatedPulseSubscriptionListApi,
    PaginatedPulseWatchedCandidateListApi,
    PatchedPulseSubscriptionApi,
    PulseDigestApi,
    PulseDigestsListParams,
    PulseFindingApi,
    PulseFindingsListParams,
    PulseScanConfigApi,
    PulseSubscriptionApi,
    PulseSubscriptionsListParams,
    TriggerScanResponseApi,
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

export const getPulseDigestsListUrl = (projectId: string, params?: PulseDigestsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/pulse_digests/?${stringifiedParams}`
        : `/api/projects/${projectId}/pulse_digests/`
}

export const pulseDigestsList = async (
    projectId: string,
    params?: PulseDigestsListParams,
    options?: RequestInit
): Promise<PaginatedPulseDigestListListApi> => {
    return apiMutator<PaginatedPulseDigestListListApi>(getPulseDigestsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPulseDigestsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse_digests/${id}/`
}

export const pulseDigestsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PulseDigestApi> => {
    return apiMutator<PulseDigestApi>(getPulseDigestsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getPulseDigestsTriggerScanCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/pulse_digests/trigger_scan/`
}

/**
 * Kick off a one-off Pulse scan for this team now, without waiting for the schedule.
 *
 * Staff-only for now (404 hides it from non-staff); the gate can be relaxed to expose it to users later.
 *
 * An optional body of tuning knobs (PulseScanConfig) overrides the heuristics for this run only —
 * nothing is persisted. The override is staff-gated by the same 404 as the trigger itself. With no
 * body, the run resolves its detection thresholds from the team's PulseSubscription, as a scheduled
 * run would.
 */
export const pulseDigestsTriggerScanCreate = async (
    projectId: string,
    pulseScanConfigApi?: PulseScanConfigApi,
    options?: RequestInit
): Promise<TriggerScanResponseApi> => {
    return apiMutator<TriggerScanResponseApi>(getPulseDigestsTriggerScanCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(pulseScanConfigApi),
    })
}

export const getPulseFindingsListUrl = (projectId: string, params?: PulseFindingsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/pulse_findings/?${stringifiedParams}`
        : `/api/projects/${projectId}/pulse_findings/`
}

export const pulseFindingsList = async (
    projectId: string,
    params?: PulseFindingsListParams,
    options?: RequestInit
): Promise<PaginatedPulseFindingListApi> => {
    return apiMutator<PaginatedPulseFindingListApi>(getPulseFindingsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPulseFindingsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse_findings/${id}/`
}

export const pulseFindingsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PulseFindingApi> => {
    return apiMutator<PulseFindingApi>(getPulseFindingsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getPulseSubscriptionsListUrl = (projectId: string, params?: PulseSubscriptionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/pulse_subscriptions/?${stringifiedParams}`
        : `/api/projects/${projectId}/pulse_subscriptions/`
}

export const pulseSubscriptionsList = async (
    projectId: string,
    params?: PulseSubscriptionsListParams,
    options?: RequestInit
): Promise<PaginatedPulseSubscriptionListApi> => {
    return apiMutator<PaginatedPulseSubscriptionListApi>(getPulseSubscriptionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPulseSubscriptionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/pulse_subscriptions/`
}

export const pulseSubscriptionsCreate = async (
    projectId: string,
    pulseSubscriptionApi?: NonReadonly<PulseSubscriptionApi>,
    options?: RequestInit
): Promise<PulseSubscriptionApi> => {
    return apiMutator<PulseSubscriptionApi>(getPulseSubscriptionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(pulseSubscriptionApi),
    })
}

export const getPulseSubscriptionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse_subscriptions/${id}/`
}

export const pulseSubscriptionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PulseSubscriptionApi> => {
    return apiMutator<PulseSubscriptionApi>(getPulseSubscriptionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getPulseSubscriptionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse_subscriptions/${id}/`
}

export const pulseSubscriptionsUpdate = async (
    projectId: string,
    id: string,
    pulseSubscriptionApi?: NonReadonly<PulseSubscriptionApi>,
    options?: RequestInit
): Promise<PulseSubscriptionApi> => {
    return apiMutator<PulseSubscriptionApi>(getPulseSubscriptionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(pulseSubscriptionApi),
    })
}

export const getPulseSubscriptionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse_subscriptions/${id}/`
}

export const pulseSubscriptionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedPulseSubscriptionApi?: NonReadonly<PatchedPulseSubscriptionApi>,
    options?: RequestInit
): Promise<PulseSubscriptionApi> => {
    return apiMutator<PulseSubscriptionApi>(getPulseSubscriptionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedPulseSubscriptionApi),
    })
}

export const getPulseSubscriptionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse_subscriptions/${id}/`
}

export const pulseSubscriptionsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPulseSubscriptionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getPulseSubscriptionsCurrentRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/pulse_subscriptions/current/`
}

export const pulseSubscriptionsCurrentRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<PulseSubscriptionApi> => {
    return apiMutator<PulseSubscriptionApi>(getPulseSubscriptionsCurrentRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getPulseSubscriptionsWatchedRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/pulse_subscriptions/watched/`
}

export const pulseSubscriptionsWatchedRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<PaginatedPulseWatchedCandidateListApi> => {
    return apiMutator<PaginatedPulseWatchedCandidateListApi>(getPulseSubscriptionsWatchedRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
