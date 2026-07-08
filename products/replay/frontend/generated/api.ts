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
    PaginatedSessionRecordingListApi,
    PaginatedSessionRecordingPlaylistListApi,
    PaginatedSingleSessionSummaryMinimalListApi,
    PatchedSessionRecordingApi,
    PatchedSessionRecordingPlaylistApi,
    SessionRecordingApi,
    SessionRecordingBulkDeleteRequestApi,
    SessionRecordingBulkDeleteResponseApi,
    SessionRecordingPlaylistApi,
    SessionRecordingPlaylistsListParams,
    SessionRecordingsListParams,
    SessionSummariesApi,
    SingleSessionSummariesListParams,
    SingleSessionSummaryApi,
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

export const getSessionRecordingPlaylistsListUrl = (
    projectId: string,
    params?: SessionRecordingPlaylistsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/session_recording_playlists/?${stringifiedParams}`
        : `/api/projects/${projectId}/session_recording_playlists/`
}

/**
 * Override list to include synthetic playlists.
 *
 * Synthetics have no DB row, so we compute each one's position in the merged
 * sort and split the requested page between synthetics and a DB queryset slice.
 * The merge/rank/sort is all in-memory, so each phase is wrapped in a span and
 * the input sizes are recorded as span attributes — a slow response on a team
 * with many playlists then shows up as a wide span against a large db_count.
 */
export const sessionRecordingPlaylistsList = async (
    projectId: string,
    params?: SessionRecordingPlaylistsListParams,
    options?: RequestInit
): Promise<PaginatedSessionRecordingPlaylistListApi> => {
    return apiMutator<PaginatedSessionRecordingPlaylistListApi>(
        getSessionRecordingPlaylistsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getSessionRecordingPlaylistsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/`
}

export const sessionRecordingPlaylistsCreate = async (
    projectId: string,
    sessionRecordingPlaylistApi?: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export const getSessionRecordingPlaylistsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingPlaylistsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsUpdate = async (
    projectId: string,
    shortId: string,
    sessionRecordingPlaylistApi?: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export const getSessionRecordingPlaylistsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedSessionRecordingPlaylistApi?: NonReadonly<PatchedSessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSessionRecordingPlaylistApi),
    })
}

export const getSessionRecordingPlaylistsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const sessionRecordingPlaylistsDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getSessionRecordingPlaylistsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getSessionRecordingPlaylistsRecordingsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/`
}

export const sessionRecordingPlaylistsRecordingsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingPlaylistsRecordingsCreateUrl = (
    projectId: string,
    shortId: string,
    sessionRecordingId: string
) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
}

export const sessionRecordingPlaylistsRecordingsCreate = async (
    projectId: string,
    shortId: string,
    sessionRecordingId: string,
    sessionRecordingPlaylistApi?: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsCreateUrl(projectId, shortId, sessionRecordingId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export const getSessionRecordingPlaylistsRecordingsDestroyUrl = (
    projectId: string,
    shortId: string,
    sessionRecordingId: string
) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
}

export const sessionRecordingPlaylistsRecordingsDestroy = async (
    projectId: string,
    shortId: string,
    sessionRecordingId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsDestroyUrl(projectId, shortId, sessionRecordingId), {
        ...options,
        method: 'DELETE',
    })
}

export const getSessionRecordingsListUrl = (projectId: string, params?: SessionRecordingsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/session_recordings/?${stringifiedParams}`
        : `/api/projects/${projectId}/session_recordings/`
}

export const sessionRecordingsList = async (
    projectId: string,
    params?: SessionRecordingsListParams,
    options?: RequestInit
): Promise<PaginatedSessionRecordingListApi> => {
    return apiMutator<PaginatedSessionRecordingListApi>(getSessionRecordingsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsUpdate = async (
    projectId: string,
    id: string,
    sessionRecordingApi?: NonReadonly<SessionRecordingApi>,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingApi),
    })
}

export const getSessionRecordingsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSessionRecordingApi?: NonReadonly<PatchedSessionRecordingApi>,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSessionRecordingApi),
    })
}

export const getSessionRecordingsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSessionRecordingsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getSessionRecordingsBulkDeleteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/session_recordings/bulk_delete/`
}

/**
 * Delete a batch of session recordings by session ID. Deletion is permanent and cannot be undone. IDs that don't match an existing recording are skipped and counted in `total_requested` but not `deleted_count`.
 */
export const sessionRecordingsBulkDeleteCreate = async (
    projectId: string,
    sessionRecordingBulkDeleteRequestApi: SessionRecordingBulkDeleteRequestApi,
    options?: RequestInit
): Promise<SessionRecordingBulkDeleteResponseApi> => {
    return apiMutator<SessionRecordingBulkDeleteResponseApi>(getSessionRecordingsBulkDeleteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingBulkDeleteRequestApi),
    })
}

export const getCreateSessionSummariesIndividuallyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/session_summaries/create_session_summaries_individually/`
}

/**
 * Generate AI individual summary for each session, without grouping.
 */
export const createSessionSummariesIndividually = async (
    projectId: string,
    sessionSummariesApi: SessionSummariesApi,
    options?: RequestInit
): Promise<SessionSummariesApi> => {
    return apiMutator<SessionSummariesApi>(getCreateSessionSummariesIndividuallyUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionSummariesApi),
    })
}

export const getSingleSessionSummariesListUrl = (projectId: string, params?: SingleSessionSummariesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/single_session_summaries/?${stringifiedParams}`
        : `/api/projects/${projectId}/single_session_summaries/`
}

/**
 * List stored AI-generated session summaries for the team, one row per session (latest summary kept). Use to discover which sessions have been summarized and to filter for sessions with specific problems — `has_exceptions=true`, `outcome=failure`, or a custom `session_ids` narrowing. Returns lightweight rows without the full summary JSON; use the retrieve endpoint for the per-segment / per-action detail.
 */
export const singleSessionSummariesList = async (
    projectId: string,
    params?: SingleSessionSummariesListParams,
    options?: RequestInit
): Promise<PaginatedSingleSessionSummaryMinimalListApi> => {
    return apiMutator<PaginatedSingleSessionSummaryMinimalListApi>(
        getSingleSessionSummariesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getSingleSessionSummariesRetrieveUrl = (projectId: string, sessionId: string) => {
    return `/api/projects/${projectId}/single_session_summaries/${sessionId}/`
}

/**
 * Get the latest stored AI summary for a single session by `session_id`. Returns the full `summary` JSON (segments with named timeline, per-action `abandonment` / `confusion` / `exception` flags, segment outcomes, headline `session_outcome`, optional `sentiment`), the `exception_event_ids` array, the `extra_summary_context` (e.g. `focus_area`) used at generation time, and the `run_metadata` (LLM model used, whether visual confirmation was applied). 404 if no summary has been generated for this session yet — to trigger generation, use the existing `session-recording-summarize` flow rather than this endpoint.
 */
export const singleSessionSummariesRetrieve = async (
    projectId: string,
    sessionId: string,
    options?: RequestInit
): Promise<SingleSessionSummaryApi> => {
    return apiMutator<SingleSessionSummaryApi>(getSingleSessionSummariesRetrieveUrl(projectId, sessionId), {
        ...options,
        method: 'GET',
    })
}
