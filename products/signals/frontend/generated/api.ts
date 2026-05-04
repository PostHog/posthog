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
    EmitFindingRequestApi,
    EmitFindingResponseApi,
    ForgetRequestApi,
    ForgetResponseApi,
    MemoryEntryApi,
    PaginatedMemoryEntryListApi,
    PaginatedPauseStateResponseListApi,
    PaginatedSignalAgentRunSummaryListApi,
    PaginatedSignalReportListApi,
    PaginatedSignalSourceConfigListApi,
    PatchedSignalSourceConfigApi,
    PauseResponseApi,
    PauseUntilRequestApi,
    ProjectProfileApi,
    RememberRequestApi,
    SignalAgentRunDetailApi,
    SignalReportApi,
    SignalSourceConfigApi,
    SignalUserAutonomyConfigApi,
    SignalsAgentMemoryListParams,
    SignalsAgentRunsListParams,
    SignalsProcessingListParams,
    SignalsReportsListParams,
    SignalsSourceConfigsListParams,
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
 * Return `SignalMemory` entries for this project. ILIKE matches on `content`; tags filter via Postgres array overlap. Expired `agent_inference` entries are hidden by default.
 * @summary Search durable memories
 */
export const getSignalsAgentMemoryListUrl = (projectId: string, params?: SignalsAgentMemoryListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/agent/memory/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/agent/memory/`
}

export const signalsAgentMemoryList = async (
    projectId: string,
    params?: SignalsAgentMemoryListParams,
    options?: RequestInit
): Promise<PaginatedMemoryEntryListApi> => {
    return apiMutator<PaginatedMemoryEntryListApi>(getSignalsAgentMemoryListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Upsert an `agent_inference` memory keyed on `(team, key)`. Re-using a key updates the existing entry in place and resets its TTL. Cannot overwrite `human_confirmed` entries.
 * @summary Write or refresh an agent memory
 */
export const getSignalsAgentMemoryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/agent/memory/`
}

export const signalsAgentMemoryCreate = async (
    projectId: string,
    rememberRequestApi: RememberRequestApi,
    options?: RequestInit
): Promise<MemoryEntryApi> => {
    return apiMutator<MemoryEntryApi>(getSignalsAgentMemoryCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(rememberRequestApi),
    })
}

/**
 * Delete an `agent_inference` entry by key. Returns `deleted=false` if no row matched. Cannot delete `human_confirmed` entries — those are human-managed only.
 * @summary Delete an agent memory by key
 */
export const getSignalsAgentMemoryDeleteUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/agent/memory/delete/`
}

export const signalsAgentMemoryDelete = async (
    projectId: string,
    forgetRequestApi: ForgetRequestApi,
    options?: RequestInit
): Promise<ForgetResponseApi> => {
    return apiMutator<ForgetResponseApi>(getSignalsAgentMemoryDeleteUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(forgetRequestApi),
    })
}

/**
 * Return the team's deterministic project profile. The response always reflects either the newest non-expired cached row or a freshly-built one (lazy compute on cache miss). Read this at the start of a run to orient on the team's product mix, integrations, warehouse sources, signal coverage, and existing inbox surface.
 * @summary Get the current project profile
 */
export const getSignalsAgentProjectProfileGetUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/agent/project_profile/`
}

export const signalsAgentProjectProfileGet = async (
    projectId: string,
    options?: RequestInit
): Promise<ProjectProfileApi[]> => {
    return apiMutator<ProjectProfileApi[]>(getSignalsAgentProjectProfileGetUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Return the most recent `SignalAgentRun` summaries for this project, newest first. Used by the headless agent to dedupe against work other runs already covered. ILIKE matches on `summary`; results are capped at 100.
 * @summary Search recent agent runs
 */
export const getSignalsAgentRunsListUrl = (projectId: string, params?: SignalsAgentRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/agent/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/agent/runs/`
}

export const signalsAgentRunsList = async (
    projectId: string,
    params?: SignalsAgentRunsListParams,
    options?: RequestInit
): Promise<PaginatedSignalAgentRunSummaryListApi> => {
    return apiMutator<PaginatedSignalAgentRunSummaryListApi>(getSignalsAgentRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Return the full `SignalAgentRun` row including `summary`, `findings`, `hypotheses_considered`, `tool_call_log`, and `metadata`. Strictly team-scoped — a UUID belonging to another team returns 404.
 * @summary Get a run by ID
 */
export const getSignalsAgentRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/agent/runs/${id}/`
}

export const signalsAgentRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SignalAgentRunDetailApi> => {
    return apiMutator<SignalAgentRunDetailApi>(getSignalsAgentRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Persist a finding to `SignalAgentRun.findings` and fire `emit_signal` with `source_product = signals_agent`. Idempotent on `(run_id, finding_id)` — a second call with the same `finding_id` short-circuits without re-firing the pipeline. Honors the team's `shadow_mode` flag: when true, the finding is persisted but the external emit is a no-op.
 * @summary Emit a finding for a run
 */
export const getSignalsAgentRunsFindingsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/agent/runs/${id}/findings/`
}

export const signalsAgentRunsFindingsCreate = async (
    projectId: string,
    id: string,
    emitFindingRequestApi: EmitFindingRequestApi,
    options?: RequestInit
): Promise<EmitFindingResponseApi> => {
    return apiMutator<EmitFindingResponseApi>(getSignalsAgentRunsFindingsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(emitFindingRequestApi),
    })
}

/**
 * Return current processing state including pause status.
 */
export const getSignalsProcessingListUrl = (projectId: string, params?: SignalsProcessingListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/processing/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/processing/`
}

export const signalsProcessingList = async (
    projectId: string,
    params?: SignalsProcessingListParams,
    options?: RequestInit
): Promise<PaginatedPauseStateResponseListApi> => {
    return apiMutator<PaginatedPauseStateResponseListApi>(getSignalsProcessingListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * View and control signal processing pipeline state for a team.
 */
export const getSignalsProcessingPauseUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/processing/pause/`
}

export const signalsProcessingPauseUpdate = async (
    projectId: string,
    pauseUntilRequestApi: PauseUntilRequestApi,
    options?: RequestInit
): Promise<PauseResponseApi> => {
    return apiMutator<PauseResponseApi>(getSignalsProcessingPauseUpdateUrl(projectId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(pauseUntilRequestApi),
    })
}

/**
 * View and control signal processing pipeline state for a team.
 */
export const getSignalsProcessingPauseDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/processing/pause/`
}

export const signalsProcessingPauseDestroy = async (
    projectId: string,
    options?: RequestInit
): Promise<PauseResponseApi> => {
    return apiMutator<PauseResponseApi>(getSignalsProcessingPauseDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}

export const getSignalsReportsListUrl = (projectId: string, params?: SignalsReportsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/reports/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/reports/`
}

export const signalsReportsList = async (
    projectId: string,
    params?: SignalsReportsListParams,
    options?: RequestInit
): Promise<PaginatedSignalReportListApi> => {
    return apiMutator<PaginatedSignalReportListApi>(getSignalsReportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsReportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${id}/`
}

export const signalsReportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SignalReportApi> => {
    return apiMutator<SignalReportApi>(getSignalsReportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsSourceConfigsListUrl = (projectId: string, params?: SignalsSourceConfigsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/source_configs/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/source_configs/`
}

export const signalsSourceConfigsList = async (
    projectId: string,
    params?: SignalsSourceConfigsListParams,
    options?: RequestInit
): Promise<PaginatedSignalSourceConfigListApi> => {
    return apiMutator<PaginatedSignalSourceConfigListApi>(getSignalsSourceConfigsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsSourceConfigsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/source_configs/`
}

export const signalsSourceConfigsCreate = async (
    projectId: string,
    signalSourceConfigApi: NonReadonly<SignalSourceConfigApi>,
    options?: RequestInit
): Promise<SignalSourceConfigApi> => {
    return apiMutator<SignalSourceConfigApi>(getSignalsSourceConfigsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalSourceConfigApi),
    })
}

export const getSignalsSourceConfigsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/source_configs/${id}/`
}

export const signalsSourceConfigsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SignalSourceConfigApi> => {
    return apiMutator<SignalSourceConfigApi>(getSignalsSourceConfigsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsSourceConfigsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/source_configs/${id}/`
}

export const signalsSourceConfigsUpdate = async (
    projectId: string,
    id: string,
    signalSourceConfigApi: NonReadonly<SignalSourceConfigApi>,
    options?: RequestInit
): Promise<SignalSourceConfigApi> => {
    return apiMutator<SignalSourceConfigApi>(getSignalsSourceConfigsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalSourceConfigApi),
    })
}

export const getSignalsSourceConfigsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/source_configs/${id}/`
}

export const signalsSourceConfigsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSignalSourceConfigApi: NonReadonly<PatchedSignalSourceConfigApi>,
    options?: RequestInit
): Promise<SignalSourceConfigApi> => {
    return apiMutator<SignalSourceConfigApi>(getSignalsSourceConfigsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSignalSourceConfigApi),
    })
}

export const getSignalsSourceConfigsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/source_configs/${id}/`
}

export const signalsSourceConfigsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSignalsSourceConfigsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Per-user signal autonomy config (singleton keyed by user).

GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
POST   /api/users/<id>/signal_autonomy/ → create or update
DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const getUsersSignalAutonomyRetrieveUrl = (userId: string) => {
    return `/api/users/${userId}/signal_autonomy/`
}

export const usersSignalAutonomyRetrieve = async (
    userId: string,
    options?: RequestInit
): Promise<SignalUserAutonomyConfigApi> => {
    return apiMutator<SignalUserAutonomyConfigApi>(getUsersSignalAutonomyRetrieveUrl(userId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Per-user signal autonomy config (singleton keyed by user).

GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
POST   /api/users/<id>/signal_autonomy/ → create or update
DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const getUsersSignalAutonomyCreateUrl = (userId: string) => {
    return `/api/users/${userId}/signal_autonomy/`
}

export const usersSignalAutonomyCreate = async (
    userId: string,
    signalUserAutonomyConfigApi: NonReadonly<SignalUserAutonomyConfigApi>,
    options?: RequestInit
): Promise<SignalUserAutonomyConfigApi> => {
    return apiMutator<SignalUserAutonomyConfigApi>(getUsersSignalAutonomyCreateUrl(userId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalUserAutonomyConfigApi),
    })
}

/**
 * Per-user signal autonomy config (singleton keyed by user).

GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
POST   /api/users/<id>/signal_autonomy/ → create or update
DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const getUsersSignalAutonomyDestroyUrl = (userId: string) => {
    return `/api/users/${userId}/signal_autonomy/`
}

export const usersSignalAutonomyDestroy = async (userId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersSignalAutonomyDestroyUrl(userId), {
        ...options,
        method: 'DELETE',
    })
}
