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
    PaginatedUserInterviewListApi,
    PatchedUserInterviewApi,
    UserInterviewApi,
    UserInterviewsListParams,
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

export type userInterviewsListResponse200 = {
    data: PaginatedUserInterviewListApi
    status: 200
}

export type userInterviewsListResponseSuccess = userInterviewsListResponse200 & {
    headers: Headers
}
export type userInterviewsListResponse = userInterviewsListResponseSuccess

export const getUserInterviewsListUrl = (projectId: string, params?: UserInterviewsListParams) => {
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

export const userInterviewsList = async (
    projectId: string,
    params?: UserInterviewsListParams,
    options?: RequestInit
): Promise<userInterviewsListResponse> => {
    return apiMutator<userInterviewsListResponse>(getUserInterviewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type userInterviewsCreateResponse201 = {
    data: UserInterviewApi
    status: 201
}

export type userInterviewsCreateResponseSuccess = userInterviewsCreateResponse201 & {
    headers: Headers
}
export type userInterviewsCreateResponse = userInterviewsCreateResponseSuccess

export const getUserInterviewsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/user_interviews/`
}

export const userInterviewsCreate = async (
    projectId: string,
    userInterviewApi: NonReadonly<UserInterviewApi>,
    options?: RequestInit
): Promise<userInterviewsCreateResponse> => {
    const formData = new FormData()
    if (userInterviewApi.interviewee_emails !== undefined) {
        userInterviewApi.interviewee_emails.forEach((value) => formData.append(`interviewee_emails`, value))
    }
    if (userInterviewApi.summary !== undefined) {
        formData.append(`summary`, userInterviewApi.summary)
    }
    formData.append(`audio`, userInterviewApi.audio)

    return apiMutator<userInterviewsCreateResponse>(getUserInterviewsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

export type userInterviewsRetrieveResponse200 = {
    data: UserInterviewApi
    status: 200
}

export type userInterviewsRetrieveResponseSuccess = userInterviewsRetrieveResponse200 & {
    headers: Headers
}
export type userInterviewsRetrieveResponse = userInterviewsRetrieveResponseSuccess

export const getUserInterviewsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const userInterviewsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<userInterviewsRetrieveResponse> => {
    return apiMutator<userInterviewsRetrieveResponse>(getUserInterviewsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type userInterviewsUpdateResponse200 = {
    data: UserInterviewApi
    status: 200
}

export type userInterviewsUpdateResponseSuccess = userInterviewsUpdateResponse200 & {
    headers: Headers
}
export type userInterviewsUpdateResponse = userInterviewsUpdateResponseSuccess

export const getUserInterviewsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const userInterviewsUpdate = async (
    projectId: string,
    id: string,
    userInterviewApi: NonReadonly<UserInterviewApi>,
    options?: RequestInit
): Promise<userInterviewsUpdateResponse> => {
    const formData = new FormData()
    if (userInterviewApi.interviewee_emails !== undefined) {
        userInterviewApi.interviewee_emails.forEach((value) => formData.append(`interviewee_emails`, value))
    }
    if (userInterviewApi.summary !== undefined) {
        formData.append(`summary`, userInterviewApi.summary)
    }
    formData.append(`audio`, userInterviewApi.audio)

    return apiMutator<userInterviewsUpdateResponse>(getUserInterviewsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        body: formData,
    })
}

export type userInterviewsPartialUpdateResponse200 = {
    data: UserInterviewApi
    status: 200
}

export type userInterviewsPartialUpdateResponseSuccess = userInterviewsPartialUpdateResponse200 & {
    headers: Headers
}
export type userInterviewsPartialUpdateResponse = userInterviewsPartialUpdateResponseSuccess

export const getUserInterviewsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const userInterviewsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUserInterviewApi: NonReadonly<PatchedUserInterviewApi>,
    options?: RequestInit
): Promise<userInterviewsPartialUpdateResponse> => {
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

    return apiMutator<userInterviewsPartialUpdateResponse>(getUserInterviewsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        body: formData,
    })
}

export type userInterviewsDestroyResponse204 = {
    data: void
    status: 204
}

export type userInterviewsDestroyResponseSuccess = userInterviewsDestroyResponse204 & {
    headers: Headers
}
export type userInterviewsDestroyResponse = userInterviewsDestroyResponseSuccess

export const getUserInterviewsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const userInterviewsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<userInterviewsDestroyResponse> => {
    return apiMutator<userInterviewsDestroyResponse>(getUserInterviewsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
