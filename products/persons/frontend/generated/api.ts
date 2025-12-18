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
    EnvironmentsPersonsActivityRetrieve2Params,
    EnvironmentsPersonsActivityRetrieveParams,
    EnvironmentsPersonsBulkDeleteCreateParams,
    EnvironmentsPersonsCohortsRetrieveParams,
    EnvironmentsPersonsDeleteEventsCreateParams,
    EnvironmentsPersonsDeletePropertyCreateParams,
    EnvironmentsPersonsDeleteRecordingsCreateParams,
    EnvironmentsPersonsDestroyParams,
    EnvironmentsPersonsFunnelCorrelationCreateParams,
    EnvironmentsPersonsFunnelCorrelationRetrieveParams,
    EnvironmentsPersonsFunnelCreateParams,
    EnvironmentsPersonsFunnelRetrieveParams,
    EnvironmentsPersonsLifecycleRetrieveParams,
    EnvironmentsPersonsListParams,
    EnvironmentsPersonsPartialUpdateParams,
    EnvironmentsPersonsPropertiesTimelineRetrieveParams,
    EnvironmentsPersonsResetPersonDistinctIdCreateParams,
    EnvironmentsPersonsRetrieveParams,
    EnvironmentsPersonsSplitCreateParams,
    EnvironmentsPersonsStickinessRetrieveParams,
    EnvironmentsPersonsTrendsRetrieveParams,
    EnvironmentsPersonsUpdateParams,
    EnvironmentsPersonsUpdatePropertyCreateParams,
    EnvironmentsPersonsValuesRetrieveParams,
    PaginatedPersonListApi,
    PatchedPersonApi,
    PersonApi,
    PersonsActivityRetrieve2Params,
    PersonsActivityRetrieveParams,
    PersonsBulkDeleteCreateParams,
    PersonsCohortsRetrieveParams,
    PersonsDeleteEventsCreateParams,
    PersonsDeletePropertyCreateParams,
    PersonsDeleteRecordingsCreateParams,
    PersonsDestroyParams,
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
export type environmentsPersonsListResponse200 = {
    data: PaginatedPersonListApi
    status: 200
}

export type environmentsPersonsListResponseSuccess = environmentsPersonsListResponse200 & {
    headers: Headers
}
export type environmentsPersonsListResponse = environmentsPersonsListResponseSuccess

export const getEnvironmentsPersonsListUrl = (projectId: string, params?: EnvironmentsPersonsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        const explodeParameters = ['properties']

        if (Array.isArray(value) && explodeParameters.includes(key)) {
            value.forEach((v) => {
                normalizedParams.append(key, v === null ? 'null' : v.toString())
            })
            return
        }

        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/`
}

export const environmentsPersonsList = async (
    projectId: string,
    params?: EnvironmentsPersonsListParams,
    options?: RequestInit
): Promise<environmentsPersonsListResponse> => {
    return apiMutator<environmentsPersonsListResponse>(getEnvironmentsPersonsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsRetrieveResponse200 = {
    data: PersonApi
    status: 200
}

export type environmentsPersonsRetrieveResponseSuccess = environmentsPersonsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsPersonsRetrieveResponse = environmentsPersonsRetrieveResponseSuccess

export const getEnvironmentsPersonsRetrieveUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/`
}

export const environmentsPersonsRetrieve = async (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsRetrieveResponse> => {
    return apiMutator<environmentsPersonsRetrieveResponse>(getEnvironmentsPersonsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
This means that only the properties listed will be updated, but other properties won't be removed nor updated.
If you would like to remove a property use the `delete_property` endpoint.
 */
export type environmentsPersonsUpdateResponse200 = {
    data: PersonApi
    status: 200
}

export type environmentsPersonsUpdateResponseSuccess = environmentsPersonsUpdateResponse200 & {
    headers: Headers
}
export type environmentsPersonsUpdateResponse = environmentsPersonsUpdateResponseSuccess

export const getEnvironmentsPersonsUpdateUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/`
}

export const environmentsPersonsUpdate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: EnvironmentsPersonsUpdateParams,
    options?: RequestInit
): Promise<environmentsPersonsUpdateResponse> => {
    return apiMutator<environmentsPersonsUpdateResponse>(getEnvironmentsPersonsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsPartialUpdateResponse200 = {
    data: PersonApi
    status: 200
}

export type environmentsPersonsPartialUpdateResponseSuccess = environmentsPersonsPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsPersonsPartialUpdateResponse = environmentsPersonsPartialUpdateResponseSuccess

export const getEnvironmentsPersonsPartialUpdateUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsPartialUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/`
}

export const environmentsPersonsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedPersonApi: NonReadonly<PatchedPersonApi>,
    params?: EnvironmentsPersonsPartialUpdateParams,
    options?: RequestInit
): Promise<environmentsPersonsPartialUpdateResponse> => {
    return apiMutator<environmentsPersonsPartialUpdateResponse>(
        getEnvironmentsPersonsPartialUpdateUrl(projectId, id, params),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedPersonApi),
        }
    )
}

/**
 * Use this endpoint to delete individual persons. For bulk deletion, use the bulk_delete endpoint instead.
 */
export type environmentsPersonsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsPersonsDestroyResponseSuccess = environmentsPersonsDestroyResponse204 & {
    headers: Headers
}
export type environmentsPersonsDestroyResponse = environmentsPersonsDestroyResponseSuccess

export const getEnvironmentsPersonsDestroyUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsDestroyParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/`
}

export const environmentsPersonsDestroy = async (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsDestroyParams,
    options?: RequestInit
): Promise<environmentsPersonsDestroyResponse> => {
    return apiMutator<environmentsPersonsDestroyResponse>(getEnvironmentsPersonsDestroyUrl(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type environmentsPersonsActivityRetrieve2ResponseSuccess = environmentsPersonsActivityRetrieve2Response200 & {
    headers: Headers
}
export type environmentsPersonsActivityRetrieve2Response = environmentsPersonsActivityRetrieve2ResponseSuccess

export const getEnvironmentsPersonsActivityRetrieve2Url = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsActivityRetrieve2Params
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/activity/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/activity/`
}

export const environmentsPersonsActivityRetrieve2 = async (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsActivityRetrieve2Params,
    options?: RequestInit
): Promise<environmentsPersonsActivityRetrieve2Response> => {
    return apiMutator<environmentsPersonsActivityRetrieve2Response>(
        getEnvironmentsPersonsActivityRetrieve2Url(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Queue deletion of all events associated with this person. The task runs during non-peak hours.
 */
export type environmentsPersonsDeleteEventsCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsDeleteEventsCreateResponseSuccess = environmentsPersonsDeleteEventsCreateResponse200 & {
    headers: Headers
}
export type environmentsPersonsDeleteEventsCreateResponse = environmentsPersonsDeleteEventsCreateResponseSuccess

export const getEnvironmentsPersonsDeleteEventsCreateUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsDeleteEventsCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/delete_events/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/delete_events/`
}

export const environmentsPersonsDeleteEventsCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: EnvironmentsPersonsDeleteEventsCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsDeleteEventsCreateResponse> => {
    return apiMutator<environmentsPersonsDeleteEventsCreateResponse>(
        getEnvironmentsPersonsDeleteEventsCreateUrl(projectId, id, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsDeletePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsDeletePropertyCreateResponseSuccess =
    environmentsPersonsDeletePropertyCreateResponse200 & {
        headers: Headers
    }
export type environmentsPersonsDeletePropertyCreateResponse = environmentsPersonsDeletePropertyCreateResponseSuccess

export const getEnvironmentsPersonsDeletePropertyCreateUrl = (
    projectId: string,
    id: number,
    params: EnvironmentsPersonsDeletePropertyCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/delete_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/delete_property/`
}

export const environmentsPersonsDeletePropertyCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params: EnvironmentsPersonsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsDeletePropertyCreateResponse> => {
    return apiMutator<environmentsPersonsDeletePropertyCreateResponse>(
        getEnvironmentsPersonsDeletePropertyCreateUrl(projectId, id, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * Queue deletion of all recordings associated with this person.
 */
export type environmentsPersonsDeleteRecordingsCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsDeleteRecordingsCreateResponseSuccess =
    environmentsPersonsDeleteRecordingsCreateResponse200 & {
        headers: Headers
    }
export type environmentsPersonsDeleteRecordingsCreateResponse = environmentsPersonsDeleteRecordingsCreateResponseSuccess

export const getEnvironmentsPersonsDeleteRecordingsCreateUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsDeleteRecordingsCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/delete_recordings/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/delete_recordings/`
}

export const environmentsPersonsDeleteRecordingsCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: EnvironmentsPersonsDeleteRecordingsCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsDeleteRecordingsCreateResponse> => {
    return apiMutator<environmentsPersonsDeleteRecordingsCreateResponse>(
        getEnvironmentsPersonsDeleteRecordingsCreateUrl(projectId, id, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsPropertiesTimelineRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsPropertiesTimelineRetrieveResponseSuccess =
    environmentsPersonsPropertiesTimelineRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsPersonsPropertiesTimelineRetrieveResponse =
    environmentsPersonsPropertiesTimelineRetrieveResponseSuccess

export const getEnvironmentsPersonsPropertiesTimelineRetrieveUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsPropertiesTimelineRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/properties_timeline/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/properties_timeline/`
}

export const environmentsPersonsPropertiesTimelineRetrieve = async (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsPropertiesTimelineRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsPropertiesTimelineRetrieveResponse> => {
    return apiMutator<environmentsPersonsPropertiesTimelineRetrieveResponse>(
        getEnvironmentsPersonsPropertiesTimelineRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsSplitCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsSplitCreateResponseSuccess = environmentsPersonsSplitCreateResponse200 & {
    headers: Headers
}
export type environmentsPersonsSplitCreateResponse = environmentsPersonsSplitCreateResponseSuccess

export const getEnvironmentsPersonsSplitCreateUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsPersonsSplitCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/split/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/split/`
}

export const environmentsPersonsSplitCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: EnvironmentsPersonsSplitCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsSplitCreateResponse> => {
    return apiMutator<environmentsPersonsSplitCreateResponse>(
        getEnvironmentsPersonsSplitCreateUrl(projectId, id, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsUpdatePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsUpdatePropertyCreateResponseSuccess =
    environmentsPersonsUpdatePropertyCreateResponse200 & {
        headers: Headers
    }
export type environmentsPersonsUpdatePropertyCreateResponse = environmentsPersonsUpdatePropertyCreateResponseSuccess

export const getEnvironmentsPersonsUpdatePropertyCreateUrl = (
    projectId: string,
    id: number,
    params: EnvironmentsPersonsUpdatePropertyCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/${id}/update_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/update_property/`
}

export const environmentsPersonsUpdatePropertyCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params: EnvironmentsPersonsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsUpdatePropertyCreateResponse> => {
    return apiMutator<environmentsPersonsUpdatePropertyCreateResponse>(
        getEnvironmentsPersonsUpdatePropertyCreateUrl(projectId, id, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsActivityRetrieveResponseSuccess = environmentsPersonsActivityRetrieveResponse200 & {
    headers: Headers
}
export type environmentsPersonsActivityRetrieveResponse = environmentsPersonsActivityRetrieveResponseSuccess

export const getEnvironmentsPersonsActivityRetrieveUrl = (
    projectId: string,
    params?: EnvironmentsPersonsActivityRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/activity/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/activity/`
}

export const environmentsPersonsActivityRetrieve = async (
    projectId: string,
    params?: EnvironmentsPersonsActivityRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsActivityRetrieveResponse> => {
    return apiMutator<environmentsPersonsActivityRetrieveResponse>(
        getEnvironmentsPersonsActivityRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
 */
export type environmentsPersonsBulkDeleteCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsBulkDeleteCreateResponseSuccess = environmentsPersonsBulkDeleteCreateResponse200 & {
    headers: Headers
}
export type environmentsPersonsBulkDeleteCreateResponse = environmentsPersonsBulkDeleteCreateResponseSuccess

export const getEnvironmentsPersonsBulkDeleteCreateUrl = (
    projectId: string,
    params?: EnvironmentsPersonsBulkDeleteCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/bulk_delete/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/bulk_delete/`
}

export const environmentsPersonsBulkDeleteCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: EnvironmentsPersonsBulkDeleteCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsBulkDeleteCreateResponse> => {
    return apiMutator<environmentsPersonsBulkDeleteCreateResponse>(
        getEnvironmentsPersonsBulkDeleteCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsCohortsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsCohortsRetrieveResponseSuccess = environmentsPersonsCohortsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsPersonsCohortsRetrieveResponse = environmentsPersonsCohortsRetrieveResponseSuccess

export const getEnvironmentsPersonsCohortsRetrieveUrl = (
    projectId: string,
    params?: EnvironmentsPersonsCohortsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/cohorts/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/cohorts/`
}

export const environmentsPersonsCohortsRetrieve = async (
    projectId: string,
    params?: EnvironmentsPersonsCohortsRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsCohortsRetrieveResponse> => {
    return apiMutator<environmentsPersonsCohortsRetrieveResponse>(
        getEnvironmentsPersonsCohortsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsFunnelRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsFunnelRetrieveResponseSuccess = environmentsPersonsFunnelRetrieveResponse200 & {
    headers: Headers
}
export type environmentsPersonsFunnelRetrieveResponse = environmentsPersonsFunnelRetrieveResponseSuccess

export const getEnvironmentsPersonsFunnelRetrieveUrl = (
    projectId: string,
    params?: EnvironmentsPersonsFunnelRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/funnel/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/funnel/`
}

export const environmentsPersonsFunnelRetrieve = async (
    projectId: string,
    params?: EnvironmentsPersonsFunnelRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsFunnelRetrieveResponse> => {
    return apiMutator<environmentsPersonsFunnelRetrieveResponse>(
        getEnvironmentsPersonsFunnelRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsFunnelCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsFunnelCreateResponseSuccess = environmentsPersonsFunnelCreateResponse200 & {
    headers: Headers
}
export type environmentsPersonsFunnelCreateResponse = environmentsPersonsFunnelCreateResponseSuccess

export const getEnvironmentsPersonsFunnelCreateUrl = (
    projectId: string,
    params?: EnvironmentsPersonsFunnelCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/funnel/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/funnel/`
}

export const environmentsPersonsFunnelCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: EnvironmentsPersonsFunnelCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsFunnelCreateResponse> => {
    return apiMutator<environmentsPersonsFunnelCreateResponse>(
        getEnvironmentsPersonsFunnelCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsFunnelCorrelationRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsFunnelCorrelationRetrieveResponseSuccess =
    environmentsPersonsFunnelCorrelationRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsPersonsFunnelCorrelationRetrieveResponse =
    environmentsPersonsFunnelCorrelationRetrieveResponseSuccess

export const getEnvironmentsPersonsFunnelCorrelationRetrieveUrl = (
    projectId: string,
    params?: EnvironmentsPersonsFunnelCorrelationRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/funnel/correlation/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/funnel/correlation/`
}

export const environmentsPersonsFunnelCorrelationRetrieve = async (
    projectId: string,
    params?: EnvironmentsPersonsFunnelCorrelationRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsFunnelCorrelationRetrieveResponse> => {
    return apiMutator<environmentsPersonsFunnelCorrelationRetrieveResponse>(
        getEnvironmentsPersonsFunnelCorrelationRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsFunnelCorrelationCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsFunnelCorrelationCreateResponseSuccess =
    environmentsPersonsFunnelCorrelationCreateResponse200 & {
        headers: Headers
    }
export type environmentsPersonsFunnelCorrelationCreateResponse =
    environmentsPersonsFunnelCorrelationCreateResponseSuccess

export const getEnvironmentsPersonsFunnelCorrelationCreateUrl = (
    projectId: string,
    params?: EnvironmentsPersonsFunnelCorrelationCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/funnel/correlation/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/funnel/correlation/`
}

export const environmentsPersonsFunnelCorrelationCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: EnvironmentsPersonsFunnelCorrelationCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsFunnelCorrelationCreateResponse> => {
    return apiMutator<environmentsPersonsFunnelCorrelationCreateResponse>(
        getEnvironmentsPersonsFunnelCorrelationCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsLifecycleRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsLifecycleRetrieveResponseSuccess = environmentsPersonsLifecycleRetrieveResponse200 & {
    headers: Headers
}
export type environmentsPersonsLifecycleRetrieveResponse = environmentsPersonsLifecycleRetrieveResponseSuccess

export const getEnvironmentsPersonsLifecycleRetrieveUrl = (
    projectId: string,
    params?: EnvironmentsPersonsLifecycleRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/lifecycle/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/lifecycle/`
}

export const environmentsPersonsLifecycleRetrieve = async (
    projectId: string,
    params?: EnvironmentsPersonsLifecycleRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsLifecycleRetrieveResponse> => {
    return apiMutator<environmentsPersonsLifecycleRetrieveResponse>(
        getEnvironmentsPersonsLifecycleRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.
 */
export type environmentsPersonsResetPersonDistinctIdCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsResetPersonDistinctIdCreateResponseSuccess =
    environmentsPersonsResetPersonDistinctIdCreateResponse200 & {
        headers: Headers
    }
export type environmentsPersonsResetPersonDistinctIdCreateResponse =
    environmentsPersonsResetPersonDistinctIdCreateResponseSuccess

export const getEnvironmentsPersonsResetPersonDistinctIdCreateUrl = (
    projectId: string,
    params?: EnvironmentsPersonsResetPersonDistinctIdCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/reset_person_distinct_id/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/reset_person_distinct_id/`
}

export const environmentsPersonsResetPersonDistinctIdCreate = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: EnvironmentsPersonsResetPersonDistinctIdCreateParams,
    options?: RequestInit
): Promise<environmentsPersonsResetPersonDistinctIdCreateResponse> => {
    return apiMutator<environmentsPersonsResetPersonDistinctIdCreateResponse>(
        getEnvironmentsPersonsResetPersonDistinctIdCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsStickinessRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsStickinessRetrieveResponseSuccess = environmentsPersonsStickinessRetrieveResponse200 & {
    headers: Headers
}
export type environmentsPersonsStickinessRetrieveResponse = environmentsPersonsStickinessRetrieveResponseSuccess

export const getEnvironmentsPersonsStickinessRetrieveUrl = (
    projectId: string,
    params?: EnvironmentsPersonsStickinessRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/stickiness/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/stickiness/`
}

export const environmentsPersonsStickinessRetrieve = async (
    projectId: string,
    params?: EnvironmentsPersonsStickinessRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsStickinessRetrieveResponse> => {
    return apiMutator<environmentsPersonsStickinessRetrieveResponse>(
        getEnvironmentsPersonsStickinessRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsTrendsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsTrendsRetrieveResponseSuccess = environmentsPersonsTrendsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsPersonsTrendsRetrieveResponse = environmentsPersonsTrendsRetrieveResponseSuccess

export const getEnvironmentsPersonsTrendsRetrieveUrl = (
    projectId: string,
    params?: EnvironmentsPersonsTrendsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/trends/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/trends/`
}

export const environmentsPersonsTrendsRetrieve = async (
    projectId: string,
    params?: EnvironmentsPersonsTrendsRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsTrendsRetrieveResponse> => {
    return apiMutator<environmentsPersonsTrendsRetrieveResponse>(
        getEnvironmentsPersonsTrendsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type environmentsPersonsValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsPersonsValuesRetrieveResponseSuccess = environmentsPersonsValuesRetrieveResponse200 & {
    headers: Headers
}
export type environmentsPersonsValuesRetrieveResponse = environmentsPersonsValuesRetrieveResponseSuccess

export const getEnvironmentsPersonsValuesRetrieveUrl = (
    projectId: string,
    params?: EnvironmentsPersonsValuesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/values/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/values/`
}

export const environmentsPersonsValuesRetrieve = async (
    projectId: string,
    params?: EnvironmentsPersonsValuesRetrieveParams,
    options?: RequestInit
): Promise<environmentsPersonsValuesRetrieveResponse> => {
    return apiMutator<environmentsPersonsValuesRetrieveResponse>(
        getEnvironmentsPersonsValuesRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsListResponse200 = {
    data: PaginatedPersonListApi
    status: 200
}

export type personsListResponseSuccess = personsListResponse200 & {
    headers: Headers
}
export type personsListResponse = personsListResponseSuccess

export const getPersonsListUrl = (projectId: string, params?: PersonsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        const explodeParameters = ['properties']

        if (Array.isArray(value) && explodeParameters.includes(key)) {
            value.forEach((v) => {
                normalizedParams.append(key, v === null ? 'null' : v.toString())
            })
            return
        }

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
): Promise<personsListResponse> => {
    return apiMutator<personsListResponse>(getPersonsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsRetrieveResponse200 = {
    data: PersonApi
    status: 200
}

export type personsRetrieveResponseSuccess = personsRetrieveResponse200 & {
    headers: Headers
}
export type personsRetrieveResponse = personsRetrieveResponseSuccess

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
): Promise<personsRetrieveResponse> => {
    return apiMutator<personsRetrieveResponse>(getPersonsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
This means that only the properties listed will be updated, but other properties won't be removed nor updated.
If you would like to remove a property use the `delete_property` endpoint.
 */
export type personsUpdateResponse200 = {
    data: PersonApi
    status: 200
}

export type personsUpdateResponseSuccess = personsUpdateResponse200 & {
    headers: Headers
}
export type personsUpdateResponse = personsUpdateResponseSuccess

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
): Promise<personsUpdateResponse> => {
    return apiMutator<personsUpdateResponse>(getPersonsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsPartialUpdateResponse200 = {
    data: PersonApi
    status: 200
}

export type personsPartialUpdateResponseSuccess = personsPartialUpdateResponse200 & {
    headers: Headers
}
export type personsPartialUpdateResponse = personsPartialUpdateResponseSuccess

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
): Promise<personsPartialUpdateResponse> => {
    return apiMutator<personsPartialUpdateResponse>(getPersonsPartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedPersonApi),
    })
}

/**
 * Use this endpoint to delete individual persons. For bulk deletion, use the bulk_delete endpoint instead.
 */
export type personsDestroyResponse204 = {
    data: void
    status: 204
}

export type personsDestroyResponseSuccess = personsDestroyResponse204 & {
    headers: Headers
}
export type personsDestroyResponse = personsDestroyResponseSuccess

export const getPersonsDestroyUrl = (projectId: string, id: number, params?: PersonsDestroyParams) => {
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

export const personsDestroy = async (
    projectId: string,
    id: number,
    params?: PersonsDestroyParams,
    options?: RequestInit
): Promise<personsDestroyResponse> => {
    return apiMutator<personsDestroyResponse>(getPersonsDestroyUrl(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsActivityRetrieve2ResponseSuccess = personsActivityRetrieve2Response200 & {
    headers: Headers
}
export type personsActivityRetrieve2Response = personsActivityRetrieve2ResponseSuccess

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
): Promise<personsActivityRetrieve2Response> => {
    return apiMutator<personsActivityRetrieve2Response>(getPersonsActivityRetrieve2Url(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Queue deletion of all events associated with this person. The task runs during non-peak hours.
 */
export type personsDeleteEventsCreateResponse200 = {
    data: void
    status: 200
}

export type personsDeleteEventsCreateResponseSuccess = personsDeleteEventsCreateResponse200 & {
    headers: Headers
}
export type personsDeleteEventsCreateResponse = personsDeleteEventsCreateResponseSuccess

export const getPersonsDeleteEventsCreateUrl = (
    projectId: string,
    id: number,
    params?: PersonsDeleteEventsCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/delete_events/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/delete_events/`
}

export const personsDeleteEventsCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsDeleteEventsCreateParams,
    options?: RequestInit
): Promise<personsDeleteEventsCreateResponse> => {
    return apiMutator<personsDeleteEventsCreateResponse>(getPersonsDeleteEventsCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsDeletePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type personsDeletePropertyCreateResponseSuccess = personsDeletePropertyCreateResponse200 & {
    headers: Headers
}
export type personsDeletePropertyCreateResponse = personsDeletePropertyCreateResponseSuccess

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
): Promise<personsDeletePropertyCreateResponse> => {
    return apiMutator<personsDeletePropertyCreateResponse>(getPersonsDeletePropertyCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * Queue deletion of all recordings associated with this person.
 */
export type personsDeleteRecordingsCreateResponse200 = {
    data: void
    status: 200
}

export type personsDeleteRecordingsCreateResponseSuccess = personsDeleteRecordingsCreateResponse200 & {
    headers: Headers
}
export type personsDeleteRecordingsCreateResponse = personsDeleteRecordingsCreateResponseSuccess

export const getPersonsDeleteRecordingsCreateUrl = (
    projectId: string,
    id: number,
    params?: PersonsDeleteRecordingsCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/persons/${id}/delete_recordings/?${stringifiedParams}`
        : `/api/projects/${projectId}/persons/${id}/delete_recordings/`
}

export const personsDeleteRecordingsCreate = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsDeleteRecordingsCreateParams,
    options?: RequestInit
): Promise<personsDeleteRecordingsCreateResponse> => {
    return apiMutator<personsDeleteRecordingsCreateResponse>(
        getPersonsDeleteRecordingsCreateUrl(projectId, id, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsPropertiesTimelineRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsPropertiesTimelineRetrieveResponseSuccess = personsPropertiesTimelineRetrieveResponse200 & {
    headers: Headers
}
export type personsPropertiesTimelineRetrieveResponse = personsPropertiesTimelineRetrieveResponseSuccess

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
): Promise<personsPropertiesTimelineRetrieveResponse> => {
    return apiMutator<personsPropertiesTimelineRetrieveResponse>(
        getPersonsPropertiesTimelineRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsSplitCreateResponse200 = {
    data: void
    status: 200
}

export type personsSplitCreateResponseSuccess = personsSplitCreateResponse200 & {
    headers: Headers
}
export type personsSplitCreateResponse = personsSplitCreateResponseSuccess

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
): Promise<personsSplitCreateResponse> => {
    return apiMutator<personsSplitCreateResponse>(getPersonsSplitCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsUpdatePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type personsUpdatePropertyCreateResponseSuccess = personsUpdatePropertyCreateResponse200 & {
    headers: Headers
}
export type personsUpdatePropertyCreateResponse = personsUpdatePropertyCreateResponseSuccess

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
): Promise<personsUpdatePropertyCreateResponse> => {
    return apiMutator<personsUpdatePropertyCreateResponse>(getPersonsUpdatePropertyCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsActivityRetrieveResponseSuccess = personsActivityRetrieveResponse200 & {
    headers: Headers
}
export type personsActivityRetrieveResponse = personsActivityRetrieveResponseSuccess

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
): Promise<personsActivityRetrieveResponse> => {
    return apiMutator<personsActivityRetrieveResponse>(getPersonsActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
 */
export type personsBulkDeleteCreateResponse200 = {
    data: void
    status: 200
}

export type personsBulkDeleteCreateResponseSuccess = personsBulkDeleteCreateResponse200 & {
    headers: Headers
}
export type personsBulkDeleteCreateResponse = personsBulkDeleteCreateResponseSuccess

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
): Promise<personsBulkDeleteCreateResponse> => {
    return apiMutator<personsBulkDeleteCreateResponse>(getPersonsBulkDeleteCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsCohortsRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsCohortsRetrieveResponseSuccess = personsCohortsRetrieveResponse200 & {
    headers: Headers
}
export type personsCohortsRetrieveResponse = personsCohortsRetrieveResponseSuccess

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
): Promise<personsCohortsRetrieveResponse> => {
    return apiMutator<personsCohortsRetrieveResponse>(getPersonsCohortsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsFunnelRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsFunnelRetrieveResponseSuccess = personsFunnelRetrieveResponse200 & {
    headers: Headers
}
export type personsFunnelRetrieveResponse = personsFunnelRetrieveResponseSuccess

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
): Promise<personsFunnelRetrieveResponse> => {
    return apiMutator<personsFunnelRetrieveResponse>(getPersonsFunnelRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsFunnelCreateResponse200 = {
    data: void
    status: 200
}

export type personsFunnelCreateResponseSuccess = personsFunnelCreateResponse200 & {
    headers: Headers
}
export type personsFunnelCreateResponse = personsFunnelCreateResponseSuccess

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
): Promise<personsFunnelCreateResponse> => {
    return apiMutator<personsFunnelCreateResponse>(getPersonsFunnelCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsFunnelCorrelationRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsFunnelCorrelationRetrieveResponseSuccess = personsFunnelCorrelationRetrieveResponse200 & {
    headers: Headers
}
export type personsFunnelCorrelationRetrieveResponse = personsFunnelCorrelationRetrieveResponseSuccess

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
): Promise<personsFunnelCorrelationRetrieveResponse> => {
    return apiMutator<personsFunnelCorrelationRetrieveResponse>(
        getPersonsFunnelCorrelationRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsFunnelCorrelationCreateResponse200 = {
    data: void
    status: 200
}

export type personsFunnelCorrelationCreateResponseSuccess = personsFunnelCorrelationCreateResponse200 & {
    headers: Headers
}
export type personsFunnelCorrelationCreateResponse = personsFunnelCorrelationCreateResponseSuccess

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
): Promise<personsFunnelCorrelationCreateResponse> => {
    return apiMutator<personsFunnelCorrelationCreateResponse>(getPersonsFunnelCorrelationCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsLifecycleRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsLifecycleRetrieveResponseSuccess = personsLifecycleRetrieveResponse200 & {
    headers: Headers
}
export type personsLifecycleRetrieveResponse = personsLifecycleRetrieveResponseSuccess

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
): Promise<personsLifecycleRetrieveResponse> => {
    return apiMutator<personsLifecycleRetrieveResponse>(getPersonsLifecycleRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.
 */
export type personsResetPersonDistinctIdCreateResponse200 = {
    data: void
    status: 200
}

export type personsResetPersonDistinctIdCreateResponseSuccess = personsResetPersonDistinctIdCreateResponse200 & {
    headers: Headers
}
export type personsResetPersonDistinctIdCreateResponse = personsResetPersonDistinctIdCreateResponseSuccess

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
): Promise<personsResetPersonDistinctIdCreateResponse> => {
    return apiMutator<personsResetPersonDistinctIdCreateResponse>(
        getPersonsResetPersonDistinctIdCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(personApi),
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsStickinessRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsStickinessRetrieveResponseSuccess = personsStickinessRetrieveResponse200 & {
    headers: Headers
}
export type personsStickinessRetrieveResponse = personsStickinessRetrieveResponseSuccess

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
): Promise<personsStickinessRetrieveResponse> => {
    return apiMutator<personsStickinessRetrieveResponse>(getPersonsStickinessRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsTrendsRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsTrendsRetrieveResponseSuccess = personsTrendsRetrieveResponse200 & {
    headers: Headers
}
export type personsTrendsRetrieveResponse = personsTrendsRetrieveResponseSuccess

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
): Promise<personsTrendsRetrieveResponse> => {
    return apiMutator<personsTrendsRetrieveResponse>(getPersonsTrendsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type personsValuesRetrieveResponseSuccess = personsValuesRetrieveResponse200 & {
    headers: Headers
}
export type personsValuesRetrieveResponse = personsValuesRetrieveResponseSuccess

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
): Promise<personsValuesRetrieveResponse> => {
    return apiMutator<personsValuesRetrieveResponse>(getPersonsValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
