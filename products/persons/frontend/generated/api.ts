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
    PersonsActivityRetrieve3Params,
    PersonsActivityRetrieve4Params,
    PersonsActivityRetrieveParams,
    PersonsBulkDeleteCreate2Params,
    PersonsBulkDeleteCreateParams,
    PersonsCohortsRetrieve2Params,
    PersonsCohortsRetrieveParams,
    PersonsDeletePropertyCreate2Params,
    PersonsDeletePropertyCreateParams,
    PersonsFunnelCorrelationCreate2Params,
    PersonsFunnelCorrelationCreateParams,
    PersonsFunnelCorrelationRetrieve2Params,
    PersonsFunnelCorrelationRetrieveParams,
    PersonsFunnelCreate2Params,
    PersonsFunnelCreateParams,
    PersonsFunnelRetrieve2Params,
    PersonsFunnelRetrieveParams,
    PersonsLifecycleRetrieve2Params,
    PersonsLifecycleRetrieveParams,
    PersonsList2Params,
    PersonsListParams,
    PersonsPartialUpdate2Params,
    PersonsPartialUpdateParams,
    PersonsPropertiesTimelineRetrieve2Params,
    PersonsPropertiesTimelineRetrieveParams,
    PersonsResetPersonDistinctIdCreate2Params,
    PersonsResetPersonDistinctIdCreateParams,
    PersonsRetrieve2Params,
    PersonsRetrieveParams,
    PersonsSplitCreate2Params,
    PersonsSplitCreateParams,
    PersonsStickinessRetrieve2Params,
    PersonsStickinessRetrieveParams,
    PersonsTrendsRetrieve2Params,
    PersonsTrendsRetrieveParams,
    PersonsUpdate2Params,
    PersonsUpdateParams,
    PersonsUpdatePropertyCreate2Params,
    PersonsUpdatePropertyCreateParams,
    PersonsValuesRetrieve2Params,
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
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/persons/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/`
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
        ? `/api/environments/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/`
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
        ? `/api/environments/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/`
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
        ? `/api/environments/${projectId}/persons/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/`
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
        ? `/api/environments/${projectId}/persons/${id}/activity/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/activity/`
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
        ? `/api/environments/${projectId}/persons/${id}/delete_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/delete_property/`
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
        ? `/api/environments/${projectId}/persons/${id}/properties_timeline/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/properties_timeline/`
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
        ? `/api/environments/${projectId}/persons/${id}/split/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/split/`
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
        ? `/api/environments/${projectId}/persons/${id}/update_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/${id}/update_property/`
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
        ? `/api/environments/${projectId}/persons/activity/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/activity/`
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
        ? `/api/environments/${projectId}/persons/bulk_delete/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/bulk_delete/`
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
        ? `/api/environments/${projectId}/persons/cohorts/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/cohorts/`
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
        ? `/api/environments/${projectId}/persons/funnel/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/funnel/`
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
        ? `/api/environments/${projectId}/persons/funnel/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/funnel/`
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
        ? `/api/environments/${projectId}/persons/funnel/correlation/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/funnel/correlation/`
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
        ? `/api/environments/${projectId}/persons/funnel/correlation/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/funnel/correlation/`
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
        ? `/api/environments/${projectId}/persons/lifecycle/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/lifecycle/`
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
        ? `/api/environments/${projectId}/persons/reset_person_distinct_id/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/reset_person_distinct_id/`
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
        ? `/api/environments/${projectId}/persons/stickiness/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/stickiness/`
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
        ? `/api/environments/${projectId}/persons/trends/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/trends/`
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
        ? `/api/environments/${projectId}/persons/values/?${stringifiedParams}`
        : `/api/environments/${projectId}/persons/values/`
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

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsList2Response200 = {
    data: PaginatedPersonListApi
    status: 200
}

export type personsList2ResponseSuccess = personsList2Response200 & {
    headers: Headers
}
export type personsList2Response = personsList2ResponseSuccess

export const getPersonsList2Url = (projectId: string, params?: PersonsList2Params) => {
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

export const personsList2 = async (
    projectId: string,
    params?: PersonsList2Params,
    options?: RequestInit
): Promise<personsList2Response> => {
    return apiMutator<personsList2Response>(getPersonsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsRetrieve2Response200 = {
    data: PersonApi
    status: 200
}

export type personsRetrieve2ResponseSuccess = personsRetrieve2Response200 & {
    headers: Headers
}
export type personsRetrieve2Response = personsRetrieve2ResponseSuccess

export const getPersonsRetrieve2Url = (projectId: string, id: number, params?: PersonsRetrieve2Params) => {
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

export const personsRetrieve2 = async (
    projectId: string,
    id: number,
    params?: PersonsRetrieve2Params,
    options?: RequestInit
): Promise<personsRetrieve2Response> => {
    return apiMutator<personsRetrieve2Response>(getPersonsRetrieve2Url(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
This means that only the properties listed will be updated, but other properties won't be removed nor updated.
If you would like to remove a property use the `delete_property` endpoint.
 */
export type personsUpdate2Response200 = {
    data: PersonApi
    status: 200
}

export type personsUpdate2ResponseSuccess = personsUpdate2Response200 & {
    headers: Headers
}
export type personsUpdate2Response = personsUpdate2ResponseSuccess

export const getPersonsUpdate2Url = (projectId: string, id: number, params?: PersonsUpdate2Params) => {
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

export const personsUpdate2 = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsUpdate2Params,
    options?: RequestInit
): Promise<personsUpdate2Response> => {
    return apiMutator<personsUpdate2Response>(getPersonsUpdate2Url(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsPartialUpdate2Response200 = {
    data: PersonApi
    status: 200
}

export type personsPartialUpdate2ResponseSuccess = personsPartialUpdate2Response200 & {
    headers: Headers
}
export type personsPartialUpdate2Response = personsPartialUpdate2ResponseSuccess

export const getPersonsPartialUpdate2Url = (projectId: string, id: number, params?: PersonsPartialUpdate2Params) => {
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

export const personsPartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedPersonApi: NonReadonly<PatchedPersonApi>,
    params?: PersonsPartialUpdate2Params,
    options?: RequestInit
): Promise<personsPartialUpdate2Response> => {
    return apiMutator<personsPartialUpdate2Response>(getPersonsPartialUpdate2Url(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedPersonApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsActivityRetrieve4Response200 = {
    data: void
    status: 200
}

export type personsActivityRetrieve4ResponseSuccess = personsActivityRetrieve4Response200 & {
    headers: Headers
}
export type personsActivityRetrieve4Response = personsActivityRetrieve4ResponseSuccess

export const getPersonsActivityRetrieve4Url = (
    projectId: string,
    id: number,
    params?: PersonsActivityRetrieve4Params
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

export const personsActivityRetrieve4 = async (
    projectId: string,
    id: number,
    params?: PersonsActivityRetrieve4Params,
    options?: RequestInit
): Promise<personsActivityRetrieve4Response> => {
    return apiMutator<personsActivityRetrieve4Response>(getPersonsActivityRetrieve4Url(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsDeletePropertyCreate2Response200 = {
    data: void
    status: 200
}

export type personsDeletePropertyCreate2ResponseSuccess = personsDeletePropertyCreate2Response200 & {
    headers: Headers
}
export type personsDeletePropertyCreate2Response = personsDeletePropertyCreate2ResponseSuccess

export const getPersonsDeletePropertyCreate2Url = (
    projectId: string,
    id: number,
    params: PersonsDeletePropertyCreate2Params
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

export const personsDeletePropertyCreate2 = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params: PersonsDeletePropertyCreate2Params,
    options?: RequestInit
): Promise<personsDeletePropertyCreate2Response> => {
    return apiMutator<personsDeletePropertyCreate2Response>(getPersonsDeletePropertyCreate2Url(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsPropertiesTimelineRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsPropertiesTimelineRetrieve2ResponseSuccess = personsPropertiesTimelineRetrieve2Response200 & {
    headers: Headers
}
export type personsPropertiesTimelineRetrieve2Response = personsPropertiesTimelineRetrieve2ResponseSuccess

export const getPersonsPropertiesTimelineRetrieve2Url = (
    projectId: string,
    id: number,
    params?: PersonsPropertiesTimelineRetrieve2Params
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

export const personsPropertiesTimelineRetrieve2 = async (
    projectId: string,
    id: number,
    params?: PersonsPropertiesTimelineRetrieve2Params,
    options?: RequestInit
): Promise<personsPropertiesTimelineRetrieve2Response> => {
    return apiMutator<personsPropertiesTimelineRetrieve2Response>(
        getPersonsPropertiesTimelineRetrieve2Url(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsSplitCreate2Response200 = {
    data: void
    status: 200
}

export type personsSplitCreate2ResponseSuccess = personsSplitCreate2Response200 & {
    headers: Headers
}
export type personsSplitCreate2Response = personsSplitCreate2ResponseSuccess

export const getPersonsSplitCreate2Url = (projectId: string, id: number, params?: PersonsSplitCreate2Params) => {
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

export const personsSplitCreate2 = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsSplitCreate2Params,
    options?: RequestInit
): Promise<personsSplitCreate2Response> => {
    return apiMutator<personsSplitCreate2Response>(getPersonsSplitCreate2Url(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsUpdatePropertyCreate2Response200 = {
    data: void
    status: 200
}

export type personsUpdatePropertyCreate2ResponseSuccess = personsUpdatePropertyCreate2Response200 & {
    headers: Headers
}
export type personsUpdatePropertyCreate2Response = personsUpdatePropertyCreate2ResponseSuccess

export const getPersonsUpdatePropertyCreate2Url = (
    projectId: string,
    id: number,
    params: PersonsUpdatePropertyCreate2Params
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

export const personsUpdatePropertyCreate2 = async (
    projectId: string,
    id: number,
    personApi: NonReadonly<PersonApi>,
    params: PersonsUpdatePropertyCreate2Params,
    options?: RequestInit
): Promise<personsUpdatePropertyCreate2Response> => {
    return apiMutator<personsUpdatePropertyCreate2Response>(getPersonsUpdatePropertyCreate2Url(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsActivityRetrieve3Response200 = {
    data: void
    status: 200
}

export type personsActivityRetrieve3ResponseSuccess = personsActivityRetrieve3Response200 & {
    headers: Headers
}
export type personsActivityRetrieve3Response = personsActivityRetrieve3ResponseSuccess

export const getPersonsActivityRetrieve3Url = (projectId: string, params?: PersonsActivityRetrieve3Params) => {
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

export const personsActivityRetrieve3 = async (
    projectId: string,
    params?: PersonsActivityRetrieve3Params,
    options?: RequestInit
): Promise<personsActivityRetrieve3Response> => {
    return apiMutator<personsActivityRetrieve3Response>(getPersonsActivityRetrieve3Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
 */
export type personsBulkDeleteCreate2Response200 = {
    data: void
    status: 200
}

export type personsBulkDeleteCreate2ResponseSuccess = personsBulkDeleteCreate2Response200 & {
    headers: Headers
}
export type personsBulkDeleteCreate2Response = personsBulkDeleteCreate2ResponseSuccess

export const getPersonsBulkDeleteCreate2Url = (projectId: string, params?: PersonsBulkDeleteCreate2Params) => {
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

export const personsBulkDeleteCreate2 = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsBulkDeleteCreate2Params,
    options?: RequestInit
): Promise<personsBulkDeleteCreate2Response> => {
    return apiMutator<personsBulkDeleteCreate2Response>(getPersonsBulkDeleteCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsCohortsRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsCohortsRetrieve2ResponseSuccess = personsCohortsRetrieve2Response200 & {
    headers: Headers
}
export type personsCohortsRetrieve2Response = personsCohortsRetrieve2ResponseSuccess

export const getPersonsCohortsRetrieve2Url = (projectId: string, params?: PersonsCohortsRetrieve2Params) => {
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

export const personsCohortsRetrieve2 = async (
    projectId: string,
    params?: PersonsCohortsRetrieve2Params,
    options?: RequestInit
): Promise<personsCohortsRetrieve2Response> => {
    return apiMutator<personsCohortsRetrieve2Response>(getPersonsCohortsRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsFunnelRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsFunnelRetrieve2ResponseSuccess = personsFunnelRetrieve2Response200 & {
    headers: Headers
}
export type personsFunnelRetrieve2Response = personsFunnelRetrieve2ResponseSuccess

export const getPersonsFunnelRetrieve2Url = (projectId: string, params?: PersonsFunnelRetrieve2Params) => {
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

export const personsFunnelRetrieve2 = async (
    projectId: string,
    params?: PersonsFunnelRetrieve2Params,
    options?: RequestInit
): Promise<personsFunnelRetrieve2Response> => {
    return apiMutator<personsFunnelRetrieve2Response>(getPersonsFunnelRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsFunnelCreate2Response200 = {
    data: void
    status: 200
}

export type personsFunnelCreate2ResponseSuccess = personsFunnelCreate2Response200 & {
    headers: Headers
}
export type personsFunnelCreate2Response = personsFunnelCreate2ResponseSuccess

export const getPersonsFunnelCreate2Url = (projectId: string, params?: PersonsFunnelCreate2Params) => {
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

export const personsFunnelCreate2 = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsFunnelCreate2Params,
    options?: RequestInit
): Promise<personsFunnelCreate2Response> => {
    return apiMutator<personsFunnelCreate2Response>(getPersonsFunnelCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(personApi),
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsFunnelCorrelationRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsFunnelCorrelationRetrieve2ResponseSuccess = personsFunnelCorrelationRetrieve2Response200 & {
    headers: Headers
}
export type personsFunnelCorrelationRetrieve2Response = personsFunnelCorrelationRetrieve2ResponseSuccess

export const getPersonsFunnelCorrelationRetrieve2Url = (
    projectId: string,
    params?: PersonsFunnelCorrelationRetrieve2Params
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

export const personsFunnelCorrelationRetrieve2 = async (
    projectId: string,
    params?: PersonsFunnelCorrelationRetrieve2Params,
    options?: RequestInit
): Promise<personsFunnelCorrelationRetrieve2Response> => {
    return apiMutator<personsFunnelCorrelationRetrieve2Response>(
        getPersonsFunnelCorrelationRetrieve2Url(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsFunnelCorrelationCreate2Response200 = {
    data: void
    status: 200
}

export type personsFunnelCorrelationCreate2ResponseSuccess = personsFunnelCorrelationCreate2Response200 & {
    headers: Headers
}
export type personsFunnelCorrelationCreate2Response = personsFunnelCorrelationCreate2ResponseSuccess

export const getPersonsFunnelCorrelationCreate2Url = (
    projectId: string,
    params?: PersonsFunnelCorrelationCreate2Params
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

export const personsFunnelCorrelationCreate2 = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsFunnelCorrelationCreate2Params,
    options?: RequestInit
): Promise<personsFunnelCorrelationCreate2Response> => {
    return apiMutator<personsFunnelCorrelationCreate2Response>(
        getPersonsFunnelCorrelationCreate2Url(projectId, params),
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
export type personsLifecycleRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsLifecycleRetrieve2ResponseSuccess = personsLifecycleRetrieve2Response200 & {
    headers: Headers
}
export type personsLifecycleRetrieve2Response = personsLifecycleRetrieve2ResponseSuccess

export const getPersonsLifecycleRetrieve2Url = (projectId: string, params?: PersonsLifecycleRetrieve2Params) => {
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

export const personsLifecycleRetrieve2 = async (
    projectId: string,
    params?: PersonsLifecycleRetrieve2Params,
    options?: RequestInit
): Promise<personsLifecycleRetrieve2Response> => {
    return apiMutator<personsLifecycleRetrieve2Response>(getPersonsLifecycleRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.
 */
export type personsResetPersonDistinctIdCreate2Response200 = {
    data: void
    status: 200
}

export type personsResetPersonDistinctIdCreate2ResponseSuccess = personsResetPersonDistinctIdCreate2Response200 & {
    headers: Headers
}
export type personsResetPersonDistinctIdCreate2Response = personsResetPersonDistinctIdCreate2ResponseSuccess

export const getPersonsResetPersonDistinctIdCreate2Url = (
    projectId: string,
    params?: PersonsResetPersonDistinctIdCreate2Params
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

export const personsResetPersonDistinctIdCreate2 = async (
    projectId: string,
    personApi: NonReadonly<PersonApi>,
    params?: PersonsResetPersonDistinctIdCreate2Params,
    options?: RequestInit
): Promise<personsResetPersonDistinctIdCreate2Response> => {
    return apiMutator<personsResetPersonDistinctIdCreate2Response>(
        getPersonsResetPersonDistinctIdCreate2Url(projectId, params),
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
export type personsStickinessRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsStickinessRetrieve2ResponseSuccess = personsStickinessRetrieve2Response200 & {
    headers: Headers
}
export type personsStickinessRetrieve2Response = personsStickinessRetrieve2ResponseSuccess

export const getPersonsStickinessRetrieve2Url = (projectId: string, params?: PersonsStickinessRetrieve2Params) => {
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

export const personsStickinessRetrieve2 = async (
    projectId: string,
    params?: PersonsStickinessRetrieve2Params,
    options?: RequestInit
): Promise<personsStickinessRetrieve2Response> => {
    return apiMutator<personsStickinessRetrieve2Response>(getPersonsStickinessRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsTrendsRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsTrendsRetrieve2ResponseSuccess = personsTrendsRetrieve2Response200 & {
    headers: Headers
}
export type personsTrendsRetrieve2Response = personsTrendsRetrieve2ResponseSuccess

export const getPersonsTrendsRetrieve2Url = (projectId: string, params?: PersonsTrendsRetrieve2Params) => {
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

export const personsTrendsRetrieve2 = async (
    projectId: string,
    params?: PersonsTrendsRetrieve2Params,
    options?: RequestInit
): Promise<personsTrendsRetrieve2Response> => {
    return apiMutator<personsTrendsRetrieve2Response>(getPersonsTrendsRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export type personsValuesRetrieve2Response200 = {
    data: void
    status: 200
}

export type personsValuesRetrieve2ResponseSuccess = personsValuesRetrieve2Response200 & {
    headers: Headers
}
export type personsValuesRetrieve2Response = personsValuesRetrieve2ResponseSuccess

export const getPersonsValuesRetrieve2Url = (projectId: string, params?: PersonsValuesRetrieve2Params) => {
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

export const personsValuesRetrieve2 = async (
    projectId: string,
    params?: PersonsValuesRetrieve2Params,
    options?: RequestInit
): Promise<personsValuesRetrieve2Response> => {
    return apiMutator<personsValuesRetrieve2Response>(getPersonsValuesRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}
