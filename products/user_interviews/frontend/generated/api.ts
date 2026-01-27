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
): Promise<PaginatedUserInterviewListApi> => {
    return apiMutator<PaginatedUserInterviewListApi>(getUserInterviewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUserInterviewsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/user_interviews/`
}

export const userInterviewsCreate = async (
    projectId: string,
    userInterviewApi: NonReadonly<UserInterviewApi>,
    options?: RequestInit
): Promise<UserInterviewApi> => {
    const formData = new FormData()
    if (userInterviewApi.interviewee_emails !== undefined) {
        userInterviewApi.interviewee_emails.forEach((value) => formData.append(`interviewee_emails`, value))
    }
    if (userInterviewApi.summary !== undefined) {
        formData.append(`summary`, userInterviewApi.summary)
    }
    formData.append(`audio`, userInterviewApi.audio)

    return apiMutator<UserInterviewApi>(getUserInterviewsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

export const getUserInterviewsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const userInterviewsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<UserInterviewApi> => {
    return apiMutator<UserInterviewApi>(getUserInterviewsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUserInterviewsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const userInterviewsUpdate = async (
    projectId: string,
    id: string,
    userInterviewApi: NonReadonly<UserInterviewApi>,
    options?: RequestInit
): Promise<UserInterviewApi> => {
    const formData = new FormData()
    if (userInterviewApi.interviewee_emails !== undefined) {
        userInterviewApi.interviewee_emails.forEach((value) => formData.append(`interviewee_emails`, value))
    }
    if (userInterviewApi.summary !== undefined) {
        formData.append(`summary`, userInterviewApi.summary)
    }
    formData.append(`audio`, userInterviewApi.audio)

    return apiMutator<UserInterviewApi>(getUserInterviewsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        body: formData,
    })
}

export const getUserInterviewsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const userInterviewsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUserInterviewApi: NonReadonly<PatchedUserInterviewApi>,
    options?: RequestInit
): Promise<UserInterviewApi> => {
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

    return apiMutator<UserInterviewApi>(getUserInterviewsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        body: formData,
    })
}

export const getUserInterviewsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interviews/${id}/`
}

export const userInterviewsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUserInterviewsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
