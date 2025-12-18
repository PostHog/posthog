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
    EnvironmentsUserInterviewsListParams,
    PaginatedUserInterviewListApi,
    PatchedUserInterviewApi,
    UserInterviewApi,
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

export type environmentsUserInterviewsListResponse200 = {
    data: PaginatedUserInterviewListApi
    status: 200
}

export type environmentsUserInterviewsListResponseSuccess = environmentsUserInterviewsListResponse200 & {
    headers: Headers
}
export type environmentsUserInterviewsListResponse = environmentsUserInterviewsListResponseSuccess

export const getEnvironmentsUserInterviewsListUrl = (
    projectId: string,
    params?: EnvironmentsUserInterviewsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/user_interviews/?${stringifiedParams}`
        : `/api/environments/${projectId}/user_interviews/`
}

export const environmentsUserInterviewsList = async (
    projectId: string,
    params?: EnvironmentsUserInterviewsListParams,
    options?: RequestInit
): Promise<environmentsUserInterviewsListResponse> => {
    return apiMutator<environmentsUserInterviewsListResponse>(getEnvironmentsUserInterviewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsUserInterviewsCreateResponse201 = {
    data: UserInterviewApi
    status: 201
}

export type environmentsUserInterviewsCreateResponseSuccess = environmentsUserInterviewsCreateResponse201 & {
    headers: Headers
}
export type environmentsUserInterviewsCreateResponse = environmentsUserInterviewsCreateResponseSuccess

export const getEnvironmentsUserInterviewsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/user_interviews/`
}

export const environmentsUserInterviewsCreate = async (
    projectId: string,
    userInterviewApi: NonReadonly<UserInterviewApi>,
    options?: RequestInit
): Promise<environmentsUserInterviewsCreateResponse> => {
    const formData = new FormData()
    if (userInterviewApi.interviewee_emails !== undefined) {
        userInterviewApi.interviewee_emails.forEach((value) => formData.append(`interviewee_emails`, value))
    }
    if (userInterviewApi.summary !== undefined) {
        formData.append(`summary`, userInterviewApi.summary)
    }
    formData.append(`audio`, userInterviewApi.audio)

    return apiMutator<environmentsUserInterviewsCreateResponse>(getEnvironmentsUserInterviewsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

export type environmentsUserInterviewsRetrieveResponse200 = {
    data: UserInterviewApi
    status: 200
}

export type environmentsUserInterviewsRetrieveResponseSuccess = environmentsUserInterviewsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsUserInterviewsRetrieveResponse = environmentsUserInterviewsRetrieveResponseSuccess

export const getEnvironmentsUserInterviewsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const environmentsUserInterviewsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsUserInterviewsRetrieveResponse> => {
    return apiMutator<environmentsUserInterviewsRetrieveResponse>(
        getEnvironmentsUserInterviewsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsUserInterviewsUpdateResponse200 = {
    data: UserInterviewApi
    status: 200
}

export type environmentsUserInterviewsUpdateResponseSuccess = environmentsUserInterviewsUpdateResponse200 & {
    headers: Headers
}
export type environmentsUserInterviewsUpdateResponse = environmentsUserInterviewsUpdateResponseSuccess

export const getEnvironmentsUserInterviewsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const environmentsUserInterviewsUpdate = async (
    projectId: string,
    id: string,
    userInterviewApi: NonReadonly<UserInterviewApi>,
    options?: RequestInit
): Promise<environmentsUserInterviewsUpdateResponse> => {
    const formData = new FormData()
    if (userInterviewApi.interviewee_emails !== undefined) {
        userInterviewApi.interviewee_emails.forEach((value) => formData.append(`interviewee_emails`, value))
    }
    if (userInterviewApi.summary !== undefined) {
        formData.append(`summary`, userInterviewApi.summary)
    }
    formData.append(`audio`, userInterviewApi.audio)

    return apiMutator<environmentsUserInterviewsUpdateResponse>(getEnvironmentsUserInterviewsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        body: formData,
    })
}

export type environmentsUserInterviewsPartialUpdateResponse200 = {
    data: UserInterviewApi
    status: 200
}

export type environmentsUserInterviewsPartialUpdateResponseSuccess =
    environmentsUserInterviewsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsUserInterviewsPartialUpdateResponse = environmentsUserInterviewsPartialUpdateResponseSuccess

export const getEnvironmentsUserInterviewsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const environmentsUserInterviewsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUserInterviewApi: NonReadonly<PatchedUserInterviewApi>,
    options?: RequestInit
): Promise<environmentsUserInterviewsPartialUpdateResponse> => {
    const formData = new FormData()
    if (patchedUserInterviewApi.interviewee_emails !== undefined) {
        patchedUserInterviewApi.interviewee_emails.forEach((value) => formData.append(`interviewee_emails`, value))
    }
    if (patchedUserInterviewApi.summary !== undefined) {
        formData.append(`summary`, patchedUserInterviewApi.summary)
    }
    if (patchedUserInterviewApi.audio !== undefined) {
        formData.append(`audio`, patchedUserInterviewApi.audio)
    }

    return apiMutator<environmentsUserInterviewsPartialUpdateResponse>(
        getEnvironmentsUserInterviewsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            body: formData,
        }
    )
}

export type environmentsUserInterviewsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsUserInterviewsDestroyResponseSuccess = environmentsUserInterviewsDestroyResponse204 & {
    headers: Headers
}
export type environmentsUserInterviewsDestroyResponse = environmentsUserInterviewsDestroyResponseSuccess

export const getEnvironmentsUserInterviewsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const environmentsUserInterviewsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsUserInterviewsDestroyResponse> => {
    return apiMutator<environmentsUserInterviewsDestroyResponse>(
        getEnvironmentsUserInterviewsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}
