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
    PaginatedAsyncDeletionStatusListApi,
    PaginatedPersonRecordListApi,
    PatchedPersonRecordApi,
    PersonBulkDeleteRequestApi,
    PersonBulkDeleteResponseApi,
    PersonDeletePropertyRequestApi,
    PersonPropertiesAtTimeResponseApi,
    PersonRecordApi,
    PersonSplitRequestApi,
    PersonSplitResponseApi,
    PersonUpdatePropertyRequestApi,
    PersonsActivityRetrieveParams,
    PersonsAllActivityRetrieveParams,
    PersonsBatchByDistinctIdsCreateParams,
    PersonsBatchByUuidsCreateParams,
    PersonsBulkDeleteCreateParams,
    PersonsCohortsRetrieveParams,
    PersonsDeletePropertyCreateParams,
    PersonsDeletionStatusListParams,
    PersonsFunnelCreateParams,
    PersonsFunnelRetrieveParams,
    PersonsLifecycleRetrieveParams,
    PersonsListParams,
    PersonsPartialUpdateParams,
    PersonsPropertiesAtTimeRetrieveParams,
    PersonsPropertiesTimelineRetrieveParams,
    PersonsResetPersonDistinctIdCreateParams,
    PersonsRetrieveParams,
    PersonsSplitCreateParams,
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

export const getPersonsListUrl = (projectId: string, params?: PersonsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsList = async (
    projectId: string,
    params?: PersonsListParams,
    options?: RequestInit
): Promise<PaginatedPersonRecordListApi> => {
    return apiMutator<PaginatedPersonRecordListApi>(getPersonsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPersonsRetrieveUrl = (projectId: string, id: string, params?: PersonsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsRetrieve = async (
    projectId: string,
    id: string,
    params?: PersonsRetrieveParams,
    options?: RequestInit
): Promise<PersonRecordApi> => {
    return apiMutator<PersonRecordApi>(getPersonsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getPersonsUpdateUrl = (projectId: string, id: string, params?: PersonsUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/`
}

/**
 * Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
 * This means that only the properties listed will be updated, but other properties won't be removed nor updated.
 * If you would like to remove a property use the `delete_property` endpoint.
 */
export const personsUpdate = async (
    projectId: string,
    id: string,
    personRecordApi?: NonReadonly<PersonRecordApi>,
    params?: PersonsUpdateParams,
    options?: RequestInit
): Promise<PersonRecordApi> => {
    return apiMutator<PersonRecordApi>(getPersonsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personRecordApi),
    })
}

export const getPersonsPartialUpdateUrl = (projectId: string, id: string, params?: PersonsPartialUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedPersonRecordApi?: NonReadonly<PatchedPersonRecordApi>,
    params?: PersonsPartialUpdateParams,
    options?: RequestInit
): Promise<PersonRecordApi> => {
    return apiMutator<PersonRecordApi>(getPersonsPartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedPersonRecordApi),
    })
}

export const getPersonsActivityRetrieveUrl = (
    projectId: string,
    id: number,
    params?: PersonsActivityRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/activity/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsActivityRetrieve = async (
    projectId: string,
    id: number,
    params?: PersonsActivityRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsActivityRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getPersonsDeletePropertyCreateUrl = (
    projectId: string,
    id: string,
    params?: PersonsDeletePropertyCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/delete_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/delete_property/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsDeletePropertyCreate = async (
    projectId: string,
    id: string,
    personDeletePropertyRequestApi: PersonDeletePropertyRequestApi,
    params?: PersonsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsDeletePropertyCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personDeletePropertyRequestApi),
    })
}

export const getPersonsPropertiesTimelineRetrieveUrl = (
    projectId: string,
    id: number,
    params?: PersonsPropertiesTimelineRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/properties_timeline/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/properties_timeline/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
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

export const getPersonsSplitCreateUrl = (projectId: string, id: string, params?: PersonsSplitCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/split/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/split/`
}

/**
 * Split distinct_ids off a merged person. Two mutually exclusive modes:
 *
 * - **`distinct_ids_to_split`** (recommended for surgical edits): moves only the listed distinct_ids off this person onto new single-id persons. The original person keeps every other distinct_id and its properties.
 * - **`main_distinct_id`**: keeps only the specified distinct_id on this person; moves every *other* distinct_id off onto its own new person. If omitted, the first distinct_id is kept.
 *
 * The original person always retains its properties. To clear individual properties afterward, use the `delete_property` endpoint.
 *
 * The split runs asynchronously: a 201 response means the task was enqueued. Newly-created split-off persons get a deterministic UUID derived from `(team_id, distinct_id)`, so they can be located client-side without polling. If you need to delete a split-off person after this call, prefer looking it up by that deterministic UUID rather than by distinct_id, since the latter still resolves to the original merged person until the async task completes.
 */
export const personsSplitCreate = async (
    projectId: string,
    id: string,
    personSplitRequestApi?: PersonSplitRequestApi,
    params?: PersonsSplitCreateParams,
    options?: RequestInit
): Promise<PersonSplitResponseApi> => {
    return apiMutator<PersonSplitResponseApi>(getPersonsSplitCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personSplitRequestApi),
    })
}

export const getPersonsUpdatePropertyCreateUrl = (
    projectId: string,
    id: string,
    params?: PersonsUpdatePropertyCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/update_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/update_property/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsUpdatePropertyCreate = async (
    projectId: string,
    id: string,
    personUpdatePropertyRequestApi: PersonUpdatePropertyRequestApi,
    params?: PersonsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsUpdatePropertyCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personUpdatePropertyRequestApi),
    })
}

export const getPersonsAllActivityRetrieveUrl = (projectId: string, params?: PersonsAllActivityRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/activity/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsAllActivityRetrieve = async (
    projectId: string,
    params?: PersonsAllActivityRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsAllActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPersonsBatchByDistinctIdsCreateUrl = (
    projectId: string,
    params?: PersonsBatchByDistinctIdsCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/batch_by_distinct_ids/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/batch_by_distinct_ids/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsBatchByDistinctIdsCreate = async (
    projectId: string,
    personRecordApi?: NonReadonly<PersonRecordApi>,
    params?: PersonsBatchByDistinctIdsCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsBatchByDistinctIdsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personRecordApi),
    })
}

export const getPersonsBatchByUuidsCreateUrl = (projectId: string, params?: PersonsBatchByUuidsCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/batch_by_uuids/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/batch_by_uuids/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsBatchByUuidsCreate = async (
    projectId: string,
    personRecordApi?: NonReadonly<PersonRecordApi>,
    params?: PersonsBatchByUuidsCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsBatchByUuidsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personRecordApi),
    })
}

export const getPersonsBulkDeleteCreateUrl = (projectId: string, params?: PersonsBulkDeleteCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/bulk_delete/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/bulk_delete/`
}

/**
 * This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
 */
export const personsBulkDeleteCreate = async (
    projectId: string,
    personBulkDeleteRequestApi?: PersonBulkDeleteRequestApi,
    params?: PersonsBulkDeleteCreateParams,
    options?: RequestInit
): Promise<PersonBulkDeleteResponseApi> => {
    return apiMutator<PersonBulkDeleteResponseApi>(getPersonsBulkDeleteCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personBulkDeleteRequestApi),
    })
}

export const getPersonsCohortsRetrieveUrl = (projectId: string, params: PersonsCohortsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/cohorts/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/cohorts/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsCohortsRetrieve = async (
    projectId: string,
    params: PersonsCohortsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsCohortsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPersonsDeletionStatusListUrl = (projectId: string, params?: PersonsDeletionStatusListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/deletion_status/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/deletion_status/`
}

/**
 * List the status of queued event deletions for persons. When you delete a person with `delete_events=true`, an async deletion is queued. Use this endpoint to check whether those deletions are still pending or have been completed.
 */
export const personsDeletionStatusList = async (
    projectId: string,
    params?: PersonsDeletionStatusListParams,
    options?: RequestInit
): Promise<PaginatedAsyncDeletionStatusListApi> => {
    return apiMutator<PaginatedAsyncDeletionStatusListApi>(getPersonsDeletionStatusListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPersonsFunnelRetrieveUrl = (projectId: string, params?: PersonsFunnelRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/funnel/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/funnel/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
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

export const getPersonsFunnelCreateUrl = (projectId: string, params?: PersonsFunnelCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/funnel/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/funnel/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsFunnelCreate = async (
    projectId: string,
    personRecordApi?: NonReadonly<PersonRecordApi>,
    params?: PersonsFunnelCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsFunnelCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personRecordApi),
    })
}

export const getPersonsLifecycleRetrieveUrl = (projectId: string, params?: PersonsLifecycleRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/lifecycle/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/lifecycle/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
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

export const getPersonsPropertiesAtTimeRetrieveUrl = (
    projectId: string,
    params: PersonsPropertiesAtTimeRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/properties_at_time/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/properties_at_time/`
}

/**
 * Get person properties as they existed at a specific point in time.
 *
 * This endpoint reconstructs person properties by querying ClickHouse events
 * for $set and $set_once operations up to the specified timestamp.
 *
 * Query parameters:
 * - distinct_id: The distinct_id of the person
 * - timestamp: ISO datetime string for the point in time (e.g., "2023-06-15T14:30:00Z")
 * - include_set_once: Whether to handle $set_once operations (default: false)
 */
export const personsPropertiesAtTimeRetrieve = async (
    projectId: string,
    params: PersonsPropertiesAtTimeRetrieveParams,
    options?: RequestInit
): Promise<PersonPropertiesAtTimeResponseApi> => {
    return apiMutator<PersonPropertiesAtTimeResponseApi>(getPersonsPropertiesAtTimeRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPersonsResetPersonDistinctIdCreateUrl = (
    projectId: string,
    params?: PersonsResetPersonDistinctIdCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/reset_person_distinct_id/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/reset_person_distinct_id/`
}

/**
 * Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.
 */
export const personsResetPersonDistinctIdCreate = async (
    projectId: string,
    personRecordApi?: NonReadonly<PersonRecordApi>,
    params?: PersonsResetPersonDistinctIdCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsResetPersonDistinctIdCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personRecordApi),
    })
}

export const getPersonsTrendsRetrieveUrl = (projectId: string, params?: PersonsTrendsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/trends/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/trends/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
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

export const getPersonsValuesRetrieveUrl = (projectId: string, params: PersonsValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/values/`
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const personsValuesRetrieve = async (
    projectId: string,
    params: PersonsValuesRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPersonsValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
