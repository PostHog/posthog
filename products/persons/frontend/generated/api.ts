/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    PaginatedPersonListApi,
    PatchedPersonApi,
    PersonApi,
    PersonsActivityRetrieve2Params,
    PersonsActivityRetrieveParams,
    PersonsBatchByDistinctIdsCreateParams,
    PersonsBulkDeleteCreateParams,
    PersonsCohortsRetrieveParams,
    PersonsDeletePropertyCreateParams,
    PersonsFunnelCorrelationCreateParams,
    PersonsFunnelCorrelationRetrieveParams,
    PersonsFunnelCreateParams,
    PersonsFunnelRetrieveParams,
    PersonsLifecycleRetrieveParams,
    PersonsListParams,
    PersonsPartialUpdateParams,
    PersonsPropertiesTimelineRetrieveParams,
    PersonsResetPersonDistinctIdCreateParams,
    PersonsRetrieveParams,
    PersonsSplitCreateParams,
    PersonsStickinessRetrieveParams,
    PersonsTrendsRetrieveParams,
    PersonsUpdateParams,
    PersonsUpdatePropertyCreateParams,
    PersonsValuesRetrieveParams,
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

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsListUrl = (projectId: string, params?: PersonsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/`
}

export const personsList = async (
    projectId: string,
    params?: PersonsListParams,
    options?: RequestInit
): Promise<PaginatedPersonListApi> => {
    return apiMutator<PaginatedPersonListApi>(getPersonsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsRetrieveUrl = (projectId: string, id: number, params?: PersonsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/`
}

export const personsRetrieve = async (
    projectId: string,
    id: number,
    params?: PersonsRetrieveParams,
    options?: RequestInit
): Promise<PersonApi> => {
    return apiMutator<PersonApi>(getPersonsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
This means that only the properties listed will be updated, but other properties won't be removed nor updated.
If you would like to remove a property use the `delete_property` endpoint.
 */
export const getPersonsUpdateUrl = (projectId: string, id: number, params?: PersonsUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/`
}

export const personsUpdate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsUpdateParams,
    options?: RequestInit
): Promise<PersonApi> => {
    return apiMutator<PersonApi>(getPersonsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsPartialUpdateUrl = (projectId: string, id: number, params?: PersonsPartialUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/`
}

export const personsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedPersonApi: NonReadonly<PatchedPersonApi>,
    params?: PersonsPartialUpdateParams,
    options?: RequestInit
): Promise<PersonApi> => {
    return apiMutator<PersonApi>(getPersonsPartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedPersonApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsActivityRetrieve2Url = (
    projectId: string,
    id: number,
    params?: PersonsActivityRetrieve2Params
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/activity/`
}

export const personsActivityRetrieve2 = async (
    projectId: string,
    id: number,
    params?: PersonsActivityRetrieve2Params,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsActivityRetrieve2Url(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsDeletePropertyCreateUrl = (
    projectId: string,
    id: number,
    params: PersonsDeletePropertyCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/delete_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/delete_property/`
}

export const personsDeletePropertyCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params: PersonsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsDeletePropertyCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsPropertiesTimelineRetrieveUrl = (
    projectId: string,
    id: number,
    params?: PersonsPropertiesTimelineRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/properties_timeline/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/properties_timeline/`
}

export const personsPropertiesTimelineRetrieve = async (
    projectId: string,
    id: number,
    params?: PersonsPropertiesTimelineRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsPropertiesTimelineRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsSplitCreateUrl = (projectId: string, id: number, params?: PersonsSplitCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/split/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/split/`
}

export const personsSplitCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsSplitCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsSplitCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsUpdatePropertyCreateUrl = (
    projectId: string,
    id: number,
    params: PersonsUpdatePropertyCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/update_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/update_property/`
}

export const personsUpdatePropertyCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params: PersonsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsUpdatePropertyCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsActivityRetrieveUrl = (projectId: string, params?: PersonsActivityRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/activity/`
}

export const personsActivityRetrieve = async (
    projectId: string,
    params?: PersonsActivityRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsBatchByDistinctIdsCreateUrl = (
    projectId: string,
    params?: PersonsBatchByDistinctIdsCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/batch_by_distinct_ids/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/batch_by_distinct_ids/`
}

export const personsBatchByDistinctIdsCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsBatchByDistinctIdsCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsBatchByDistinctIdsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
 */
export const getPersonsBulkDeleteCreateUrl = (projectId: string, params?: PersonsBulkDeleteCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/bulk_delete/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/bulk_delete/`
}

export const personsBulkDeleteCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsBulkDeleteCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsBulkDeleteCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsCohortsRetrieveUrl = (projectId: string, params?: PersonsCohortsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/cohorts/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/cohorts/`
}

export const personsCohortsRetrieve = async (
    projectId: string,
    params?: PersonsCohortsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsCohortsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsFunnelRetrieveUrl = (projectId: string, params?: PersonsFunnelRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/funnel/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/funnel/`
}

export const personsFunnelRetrieve = async (
    projectId: string,
    params?: PersonsFunnelRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsFunnelRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsFunnelCreateUrl = (projectId: string, params?: PersonsFunnelCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/funnel/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/funnel/`
}

export const personsFunnelCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsFunnelCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsFunnelCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsFunnelCorrelationRetrieveUrl = (
    projectId: string,
    params?: PersonsFunnelCorrelationRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/funnel/correlation/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/funnel/correlation/`
}

export const personsFunnelCorrelationRetrieve = async (
    projectId: string,
    params?: PersonsFunnelCorrelationRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsFunnelCorrelationRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsFunnelCorrelationCreateUrl = (
    projectId: string,
    params?: PersonsFunnelCorrelationCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/funnel/correlation/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/funnel/correlation/`
}

export const personsFunnelCorrelationCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsFunnelCorrelationCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsFunnelCorrelationCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsLifecycleRetrieveUrl = (projectId: string, params?: PersonsLifecycleRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/lifecycle/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/lifecycle/`
}

export const personsLifecycleRetrieve = async (
    projectId: string,
    params?: PersonsLifecycleRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsLifecycleRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.
 */
export const getPersonsResetPersonDistinctIdCreateUrl = (
    projectId: string,
    params?: PersonsResetPersonDistinctIdCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/reset_person_distinct_id/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/reset_person_distinct_id/`
}

export const personsResetPersonDistinctIdCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsResetPersonDistinctIdCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsResetPersonDistinctIdCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsStickinessRetrieveUrl = (projectId: string, params?: PersonsStickinessRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/stickiness/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/stickiness/`
}

export const personsStickinessRetrieve = async (
    projectId: string,
    params?: PersonsStickinessRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsStickinessRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsTrendsRetrieveUrl = (projectId: string, params?: PersonsTrendsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/trends/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/trends/`
}

export const personsTrendsRetrieve = async (
    projectId: string,
    params?: PersonsTrendsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsTrendsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const getPersonsValuesRetrieveUrl = (projectId: string, params?: PersonsValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/values/`
}

export const personsValuesRetrieve = async (
    projectId: string,
    params?: PersonsValuesRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
