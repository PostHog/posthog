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
    PaginatedPauseStateResponseListApi,
    PaginatedSignalReportListApi,
    PaginatedSignalSourceConfigListApi,
    PatchedSignalScoutConfigApi,
    PatchedSignalSourceConfigApi,
    PauseResponseApi,
    PauseUntilRequestApi,
    ProjectProfileApi,
    RememberRequestApi,
    ScratchpadEntryApi,
    SignalReportApi,
    SignalReportDispatchResponseApi,
    SignalReportStateRequestApi,
    SignalScoutConfigApi,
    SignalScoutRunDetailApi,
    SignalScoutRunSummaryApi,
    SignalSourceConfigApi,
    SignalUserAutonomyConfigApi,
    SignalsProcessingListParams,
    SignalsReportsListParams,
    SignalsScoutProjectProfileGetParams,
    SignalsScoutRunsListParams,
    SignalsScoutScratchpadSearchParams,
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

/**
 * Return current processing state including pause status.
 */
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

export const getSignalsProcessingPauseUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/processing/pause/`
}

/**
 * View and control signal processing pipeline state for a team.
 */
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

export const getSignalsProcessingPauseDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/processing/pause/`
}

/**
 * View and control signal processing pipeline state for a team.
 */
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

export const getSignalsReportsDispatchCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${id}/dispatch/`
}

/**
 * Dispatch this report to PostHog Code (the internal Tasks runner). Behind the signals-report-dispatch flag.

Creates an implementation Task that investigates the report and opens a PR, the same work the
autonomy auto-start path performs automatically. Idempotent: a report has at most one such Task.
 */
export const signalsReportsDispatchCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SignalReportDispatchResponseApi> => {
    return apiMutator<SignalReportDispatchResponseApi>(getSignalsReportsDispatchCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getSignalsReportsStateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${id}/state/`
}

/**
 * Transition a report to a new state. The model validates allowed transitions.

The request body is validated by SignalReportStateRequestSerializer — only the
fields it declares (state, dismissal_reason, dismissal_note, snooze_for) are read,
and only snooze_for is ever forwarded to transition_to. Any other key is ignored,
so internal transition_to kwargs (reset_weight, error, ...) can't be injected.

Body: {
    "state": "suppressed" | "potential",
    # Optional dismissal feedback (honored when state == "suppressed" or "potential"):
    "dismissal_reason": "<any string code, owned by the caller>",
    "dismissal_note": "free-form text",
    # Optional, only honored for state == "potential":
    "snooze_for": <number of additional signals before re-promotion>,
}
 */
export const signalsReportsStateCreate = async (
    projectId: string,
    id: string,
    signalReportStateRequestApi: SignalReportStateRequestApi,
    options?: RequestInit
): Promise<SignalReportApi> => {
    return apiMutator<SignalReportApi>(getSignalsReportsStateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalReportStateRequestApi),
    })
}

export const getSignalsScoutConfigListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/configs/`
}

/**
 * List the per-(team, skill) scout configs for this project — schedule (`run_interval_minutes`), `enabled`, and `emit` posture per scout.
 * @summary List scout configs
 */
export const signalsScoutConfigList = async (
    projectId: string,
    options?: RequestInit
): Promise<SignalScoutConfigApi[]> => {
    return apiMutator<SignalScoutConfigApi[]>(getSignalsScoutConfigListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutConfigUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/scout/configs/${id}/`
}

/**
 * Tune one scout: change its schedule (`run_interval_minutes`), `enabled`, or `emit` (dry-run) posture. `skill_name` is fixed. Enabling records `enabled_by` and is activity-logged since it drives spend.
 * @summary Update a scout config
 */
export const signalsScoutConfigUpdate = async (
    projectId: string,
    id: string,
    patchedSignalScoutConfigApi?: NonReadonly<PatchedSignalScoutConfigApi>,
    options?: RequestInit
): Promise<SignalScoutConfigApi> => {
    return apiMutator<SignalScoutConfigApi>(getSignalsScoutConfigUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSignalScoutConfigApi),
    })
}

export const getSignalsScoutProjectProfileGetUrl = (
    projectId: string,
    params?: SignalsScoutProjectProfileGetParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/scout/project_profile/current/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/scout/project_profile/current/`
}

/**
 * Return the team's deterministic project profile. For the internal scout token the response reflects the newest non-expired cached row or a freshly-built one (lazy compute on cache miss); `force_refresh=true` skips the cache and rebuilds from authoritative sources. Public read callers (session auth or a `signal_scout:read` PAK) get the newest cached profile, or 404 if none has been built yet — they never trigger a rebuild. Read this at the start of a run to orient on the team's product mix, integrations, warehouse sources, signal coverage, and existing inbox surface.
 * @summary Get the current project profile
 */
export const signalsScoutProjectProfileGet = async (
    projectId: string,
    params?: SignalsScoutProjectProfileGetParams,
    options?: RequestInit
): Promise<ProjectProfileApi> => {
    return apiMutator<ProjectProfileApi>(getSignalsScoutProjectProfileGetUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutRunsListUrl = (projectId: string, params?: SignalsScoutRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/scout/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/scout/runs/`
}

/**
 * Return the most recent `SignalScoutRun` summaries for this project, newest first. Used by the headless scout to dedupe against work other runs already covered. ILIKE matches on `summary`. `date_from` / `date_to` are a half-open window on `created_at` (`>= date_from`, `< date_to`); pass `date_to` on subsequent calls to walk past the 100-row cap. Results capped at 100.
 * @summary Search recent agent runs
 */
export const signalsScoutRunsList = async (
    projectId: string,
    params?: SignalsScoutRunsListParams,
    options?: RequestInit
): Promise<SignalScoutRunSummaryApi[]> => {
    return apiMutator<SignalScoutRunSummaryApi[]>(getSignalsScoutRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${id}/`
}

/**
 * Return the full `SignalScoutRun` row. Status, timing, and error flow from the linked `tasks.TaskRun`. Strictly team-scoped — a UUID belonging to another team returns 404.
 * @summary Get a run by ID
 */
export const signalsScoutRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SignalScoutRunDetailApi> => {
    return apiMutator<SignalScoutRunDetailApi>(getSignalsScoutRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutEmitSignalUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${id}/emit-signal/`
}

/**
 * Fire `emit_signal` with `source_product = signals_scout`. The `finding_id` is baked into the deterministic `Signal.source_id = run:<id>:finding:<id>` for traceability, but this is NOT idempotent — a second call with the same `finding_id` emits a second signal, so do not retry an emit that may have already succeeded.
 * @summary Emit a finding for a run
 */
export const signalsScoutEmitSignal = async (
    projectId: string,
    id: string,
    emitFindingRequestApi: EmitFindingRequestApi,
    options?: RequestInit
): Promise<EmitFindingResponseApi> => {
    return apiMutator<EmitFindingResponseApi>(getSignalsScoutEmitSignalUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(emitFindingRequestApi),
    })
}

export const getSignalsScoutScratchpadSearchUrl = (projectId: string, params?: SignalsScoutScratchpadSearchParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/scout/scratchpad/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/scout/scratchpad/`
}

/**
 * Return `SignalScratchpad` entries for this project. ILIKE matches on `content` and `key`.
 * @summary Search the scout scratchpad
 */
export const signalsScoutScratchpadSearch = async (
    projectId: string,
    params?: SignalsScoutScratchpadSearchParams,
    options?: RequestInit
): Promise<ScratchpadEntryApi[]> => {
    return apiMutator<ScratchpadEntryApi[]>(getSignalsScoutScratchpadSearchUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutScratchpadRememberUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/scratchpad/`
}

/**
 * Upsert a memory keyed on `(team, key)`. Re-using a key updates the existing entry in place.
 * @summary Remember a scratchpad entry
 */
export const signalsScoutScratchpadRemember = async (
    projectId: string,
    rememberRequestApi: RememberRequestApi,
    options?: RequestInit
): Promise<ScratchpadEntryApi> => {
    return apiMutator<ScratchpadEntryApi>(getSignalsScoutScratchpadRememberUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(rememberRequestApi),
    })
}

export const getSignalsScoutScratchpadForgetUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/scratchpad/forget/`
}

/**
 * Delete an entry by key. Returns `deleted=false` if no row matched.
 * @summary Forget a scratchpad entry by key
 */
export const signalsScoutScratchpadForget = async (
    projectId: string,
    forgetRequestApi: ForgetRequestApi,
    options?: RequestInit
): Promise<ForgetResponseApi> => {
    return apiMutator<ForgetResponseApi>(getSignalsScoutScratchpadForgetUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(forgetRequestApi),
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
    patchedSignalSourceConfigApi?: NonReadonly<PatchedSignalSourceConfigApi>,
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

export const getUsersSignalAutonomyRetrieveUrl = (userId: string) => {
    return `/api/users/${userId}/signal_autonomy/`
}

/**
 * Per-user signal autonomy config (singleton keyed by user).

GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
POST   /api/users/<id>/signal_autonomy/ → create or update
DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const usersSignalAutonomyRetrieve = async (
    userId: string,
    options?: RequestInit
): Promise<SignalUserAutonomyConfigApi> => {
    return apiMutator<SignalUserAutonomyConfigApi>(getUsersSignalAutonomyRetrieveUrl(userId), {
        ...options,
        method: 'GET',
    })
}

export const getUsersSignalAutonomyCreateUrl = (userId: string) => {
    return `/api/users/${userId}/signal_autonomy/`
}

/**
 * Per-user signal autonomy config (singleton keyed by user).

GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
POST   /api/users/<id>/signal_autonomy/ → create or update
DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const usersSignalAutonomyCreate = async (
    userId: string,
    signalUserAutonomyConfigApi?: NonReadonly<SignalUserAutonomyConfigApi>,
    options?: RequestInit
): Promise<SignalUserAutonomyConfigApi> => {
    return apiMutator<SignalUserAutonomyConfigApi>(getUsersSignalAutonomyCreateUrl(userId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalUserAutonomyConfigApi),
    })
}

export const getUsersSignalAutonomyDestroyUrl = (userId: string) => {
    return `/api/users/${userId}/signal_autonomy/`
}

/**
 * Per-user signal autonomy config (singleton keyed by user).

GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
POST   /api/users/<id>/signal_autonomy/ → create or update
DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const usersSignalAutonomyDestroy = async (userId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersSignalAutonomyDestroyUrl(userId), {
        ...options,
        method: 'DELETE',
    })
}
