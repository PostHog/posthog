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
    BulkIntervieweeContextRequestApi,
    BulkIntervieweeContextResponseApi,
    IntervieweeContextApi,
    IntervieweeIdentifierRequestApi,
    PaginatedInterviewInviteResultListApi,
    PaginatedInterviewLinkListApi,
    PaginatedIntervieweeContextListApi,
    PaginatedUserInterviewListApi,
    PaginatedUserInterviewTopicListApi,
    PatchedIntervieweeContextApi,
    PatchedUserInterviewApi,
    PatchedUserInterviewTopicApi,
    SendInvitesRequestApi,
    UserInterviewApi,
    UserInterviewSearchRequestApi,
    UserInterviewSearchResultApi,
    UserInterviewTopicApi,
    UserInterviewTopicsIntervieweesListParams,
    UserInterviewTopicsListParams,
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

export const getUserInterviewTopicsListUrl = (projectId: string, params?: UserInterviewTopicsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/user_interview_topics/?${stringifiedParams}`
        : `/api/environments/${projectId}/user_interview_topics/`
}

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const userInterviewTopicsList = async (
    projectId: string,
    params?: UserInterviewTopicsListParams,
    options?: RequestInit
): Promise<PaginatedUserInterviewTopicListApi> => {
    return apiMutator<PaginatedUserInterviewTopicListApi>(getUserInterviewTopicsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUserInterviewTopicsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/user_interview_topics/`
}

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const userInterviewTopicsCreate = async (
    projectId: string,
    userInterviewTopicApi: NonReadonly<UserInterviewTopicApi>,
    options?: RequestInit
): Promise<UserInterviewTopicApi> => {
    return apiMutator<UserInterviewTopicApi>(getUserInterviewTopicsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userInterviewTopicApi),
    })
}

export const getUserInterviewTopicsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/`
}

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const userInterviewTopicsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<UserInterviewTopicApi> => {
    return apiMutator<UserInterviewTopicApi>(getUserInterviewTopicsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUserInterviewTopicsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/`
}

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const userInterviewTopicsUpdate = async (
    projectId: string,
    id: string,
    userInterviewTopicApi: NonReadonly<UserInterviewTopicApi>,
    options?: RequestInit
): Promise<UserInterviewTopicApi> => {
    return apiMutator<UserInterviewTopicApi>(getUserInterviewTopicsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userInterviewTopicApi),
    })
}

export const getUserInterviewTopicsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/`
}

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const userInterviewTopicsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUserInterviewTopicApi?: NonReadonly<PatchedUserInterviewTopicApi>,
    options?: RequestInit
): Promise<UserInterviewTopicApi> => {
    return apiMutator<UserInterviewTopicApi>(getUserInterviewTopicsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUserInterviewTopicApi),
    })
}

export const getUserInterviewTopicsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/`
}

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const userInterviewTopicsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUserInterviewTopicsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getUserInterviewTopicsAddIntervieweeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/add_interviewee/`
}

/**
 * Add a single interviewee to this topic. Email-shaped identifiers (including the `Display Name <email@host>` form) are appended to `interviewee_emails`; everything else is appended to `interviewee_distinct_ids`. Idempotent — adding an identifier that's already present leaves the topic unchanged. Returns the updated topic.
 */
export const userInterviewTopicsAddIntervieweeCreate = async (
    projectId: string,
    id: string,
    intervieweeIdentifierRequestApi: IntervieweeIdentifierRequestApi,
    options?: RequestInit
): Promise<UserInterviewTopicApi> => {
    return apiMutator<UserInterviewTopicApi>(getUserInterviewTopicsAddIntervieweeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(intervieweeIdentifierRequestApi),
    })
}

export const getUserInterviewTopicsGenerateLinksCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/generate_links/`
}

/**
 * Generate one public interview link per targeted interviewee. Materializes an IntervieweeContext row for every identifier on the topic (without overwriting existing per-person context), and an enabled SharingConfiguration with a unique access token. The URL resolves to the public interview viewer with no PostHog auth required.
 */
export const userInterviewTopicsGenerateLinksCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PaginatedInterviewLinkListApi> => {
    return apiMutator<PaginatedInterviewLinkListApi>(getUserInterviewTopicsGenerateLinksCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getUserInterviewTopicsLinksCsvCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/links_csv/`
}

/**
 * Same materialization as generate_links, returned as a downloadable CSV. Intended for users who want to mail-merge the per-person interview links into their own email tooling.
 */
export const userInterviewTopicsLinksCsvCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<Blob> => {
    return apiMutator<Blob>(getUserInterviewTopicsLinksCsvCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getUserInterviewTopicsRemoveIntervieweeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/remove_interviewee/`
}

/**
 * Remove an interviewee from this topic. Drops the identifier from both `interviewee_emails` and `interviewee_distinct_ids`, and disables any active SharingConfiguration linked to an IntervieweeContext for that identifier on this topic so the removed person can no longer open their interview link. Idempotent — removing an identifier that isn't present is a no-op. Returns the updated topic.
 */
export const userInterviewTopicsRemoveIntervieweeCreate = async (
    projectId: string,
    id: string,
    intervieweeIdentifierRequestApi: IntervieweeIdentifierRequestApi,
    options?: RequestInit
): Promise<UserInterviewTopicApi> => {
    return apiMutator<UserInterviewTopicApi>(getUserInterviewTopicsRemoveIntervieweeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(intervieweeIdentifierRequestApi),
    })
}

export const getUserInterviewTopicsSendInvitesCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${id}/send_invites/`
}

/**
 * Generate (if needed) and email a personalized public interview link to every targeted interviewee on this topic whose identifier is an email address. Distinct-ID-only interviewees are skipped and surfaced in the response. Each invite is keyed on the underlying SharingConfiguration so re-runs after token rotation produce a fresh send.
 */
export const userInterviewTopicsSendInvitesCreate = async (
    projectId: string,
    id: string,
    sendInvitesRequestApi?: SendInvitesRequestApi,
    options?: RequestInit
): Promise<PaginatedInterviewInviteResultListApi> => {
    return apiMutator<PaginatedInterviewInviteResultListApi>(
        getUserInterviewTopicsSendInvitesCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sendInvitesRequestApi),
        }
    )
}

export const getUserInterviewTopicsIntervieweesListUrl = (
    projectId: string,
    topicId: string,
    params?: UserInterviewTopicsIntervieweesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/user_interview_topics/${topicId}/interviewees/?${stringifiedParams}`
        : `/api/environments/${projectId}/user_interview_topics/${topicId}/interviewees/`
}

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const userInterviewTopicsIntervieweesList = async (
    projectId: string,
    topicId: string,
    params?: UserInterviewTopicsIntervieweesListParams,
    options?: RequestInit
): Promise<PaginatedIntervieweeContextListApi> => {
    return apiMutator<PaginatedIntervieweeContextListApi>(
        getUserInterviewTopicsIntervieweesListUrl(projectId, topicId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getUserInterviewTopicsIntervieweesCreateUrl = (projectId: string, topicId: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${topicId}/interviewees/`
}

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const userInterviewTopicsIntervieweesCreate = async (
    projectId: string,
    topicId: string,
    intervieweeContextApi: NonReadonly<IntervieweeContextApi>,
    options?: RequestInit
): Promise<IntervieweeContextApi> => {
    return apiMutator<IntervieweeContextApi>(getUserInterviewTopicsIntervieweesCreateUrl(projectId, topicId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(intervieweeContextApi),
    })
}

export const getUserInterviewTopicsIntervieweesRetrieveUrl = (projectId: string, topicId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${topicId}/interviewees/${id}/`
}

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const userInterviewTopicsIntervieweesRetrieve = async (
    projectId: string,
    topicId: string,
    id: string,
    options?: RequestInit
): Promise<IntervieweeContextApi> => {
    return apiMutator<IntervieweeContextApi>(getUserInterviewTopicsIntervieweesRetrieveUrl(projectId, topicId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUserInterviewTopicsIntervieweesUpdateUrl = (projectId: string, topicId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${topicId}/interviewees/${id}/`
}

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const userInterviewTopicsIntervieweesUpdate = async (
    projectId: string,
    topicId: string,
    id: string,
    intervieweeContextApi: NonReadonly<IntervieweeContextApi>,
    options?: RequestInit
): Promise<IntervieweeContextApi> => {
    return apiMutator<IntervieweeContextApi>(getUserInterviewTopicsIntervieweesUpdateUrl(projectId, topicId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(intervieweeContextApi),
    })
}

export const getUserInterviewTopicsIntervieweesPartialUpdateUrl = (projectId: string, topicId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${topicId}/interviewees/${id}/`
}

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const userInterviewTopicsIntervieweesPartialUpdate = async (
    projectId: string,
    topicId: string,
    id: string,
    patchedIntervieweeContextApi?: NonReadonly<PatchedIntervieweeContextApi>,
    options?: RequestInit
): Promise<IntervieweeContextApi> => {
    return apiMutator<IntervieweeContextApi>(
        getUserInterviewTopicsIntervieweesPartialUpdateUrl(projectId, topicId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedIntervieweeContextApi),
        }
    )
}

export const getUserInterviewTopicsIntervieweesDestroyUrl = (projectId: string, topicId: string, id: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${topicId}/interviewees/${id}/`
}

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const userInterviewTopicsIntervieweesDestroy = async (
    projectId: string,
    topicId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUserInterviewTopicsIntervieweesDestroyUrl(projectId, topicId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getUserInterviewTopicsIntervieweesBulkCreateUrl = (projectId: string, topicId: string) => {
    return `/api/environments/${projectId}/user_interview_topics/${topicId}/interviewees/bulk/`
}

/**
 * Create up to 500 interviewee context rows for a topic in a single request. Rows whose (topic, interviewee_identifier) already exists are skipped — the response surfaces an `inserted_count`, a `skipped_count`, and the `skipped_identifiers` so the caller can reconcile. Items must have unique `interviewee_identifier` values within the batch.
 */
export const userInterviewTopicsIntervieweesBulkCreate = async (
    projectId: string,
    topicId: string,
    bulkIntervieweeContextRequestApi: BulkIntervieweeContextRequestApi,
    options?: RequestInit
): Promise<BulkIntervieweeContextResponseApi> => {
    return apiMutator<BulkIntervieweeContextResponseApi>(
        getUserInterviewTopicsIntervieweesBulkCreateUrl(projectId, topicId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(bulkIntervieweeContextRequestApi),
        }
    )
}

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
    patchedUserInterviewApi?: NonReadonly<PatchedUserInterviewApi>,
    options?: RequestInit
): Promise<UserInterviewApi> => {
    const formData = new FormData()
    if (patchedUserInterviewApi?.interviewee_emails !== undefined) {
        patchedUserInterviewApi?.interviewee_emails.forEach((value) => formData.append(`interviewee_emails`, value))
    }
    if (patchedUserInterviewApi?.summary !== undefined) {
        formData.append(`summary`, patchedUserInterviewApi.summary)
    }
    if (patchedUserInterviewApi?.audio !== undefined) {
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

export const getUserInterviewsSearchCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/user_interviews/search/`
}

/**
 * Embed `query` with the same model used to index interview transcripts and summaries, then return the top matches by cosine distance. Each match is a single (interview, document_type) pair — an interview can appear up to twice if both its transcript and summary score above other interviews. Useful for surfacing relevant interview snippets in natural language, without exact keyword matches.
 * @summary Search interview responses by semantic similarity
 */
export const userInterviewsSearchCreate = async (
    projectId: string,
    userInterviewSearchRequestApi: UserInterviewSearchRequestApi,
    options?: RequestInit
): Promise<UserInterviewSearchResultApi[]> => {
    return apiMutator<UserInterviewSearchResultApi[]>(getUserInterviewsSearchCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userInterviewSearchRequestApi),
    })
}
