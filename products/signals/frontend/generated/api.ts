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
    CommitDiffResponseApi,
    EditReportRequestApi,
    EditReportResponseApi,
    EmitFindingRequestApi,
    EmitFindingResponseApi,
    EmitReportRequestApi,
    EmitReportResponseApi,
    FleetFindingsSummaryApi,
    ForgetRequestApi,
    ForgetResponseApi,
    PaginatedPauseStateResponseListApi,
    PaginatedSignalReportArtefactListApi,
    PaginatedSignalReportListApi,
    PaginatedSignalSourceConfigListApi,
    PatchedSignalReportArtefactLogUpdateApi,
    PatchedSignalReportContentUpdateApi,
    PatchedSignalScoutConfigApi,
    PatchedSignalSourceConfigApi,
    PauseResponseApi,
    PauseUntilRequestApi,
    ProjectProfileApi,
    RememberRequestApi,
    ScoutEmissionReportLinkApi,
    ScoutMemberApi,
    ScoutMetadataApi,
    ScoutNotifyRequestApi,
    ScoutNotifyResponseApi,
    ScoutRunIdsBatchRequestApi,
    ScratchpadEntryApi,
    SignalReportApi,
    SignalReportArtefactApi,
    SignalReportArtefactLogCreateApi,
    SignalReportArtefactWriteResponseApi,
    SignalReportBulkStateRequestApi,
    SignalReportBulkStateResponseApi,
    SignalReportStateRequestApi,
    SignalScoutConfigApi,
    SignalScoutConfigCreateApi,
    SignalScoutEmissionApi,
    SignalScoutManualRunApi,
    SignalScoutRunDetailApi,
    SignalScoutRunSummaryApi,
    SignalSourceConfigApi,
    SignalUserAutonomyConfigApi,
    SignalsProcessingListParams,
    SignalsReportArtefactsListParams,
    SignalsReportsListParams,
    SignalsScoutMembersListParams,
    SignalsScoutProjectProfileGetParams,
    SignalsScoutRunsFindingsSummaryParams,
    SignalsScoutRunsListParams,
    SignalsScoutRunsRecentEmissionsParams,
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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

export const getSignalsReportsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${id}/`
}

/**
 * Edit the human-facing title and/or summary (description) of a signal report, addressed by id. Both fields are optional — supply only the ones you want to change; at least one is required. Every other report field (status, weights, judgments) is managed by the signals pipeline and cannot be set here. Returns the full updated report.
 * @summary Edit a report's title or summary
 */
export const signalsReportsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSignalReportContentUpdateApi?: PatchedSignalReportContentUpdateApi,
    options?: RequestInit
): Promise<SignalReportApi> => {
    return apiMutator<SignalReportApi>(getSignalsReportsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSignalReportContentUpdateApi),
    })
}

export const getSignalsReportsStateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${id}/state/`
}

/**
 * Transition a report to a new state. The model validates allowed transitions.
 *
 * The request body is validated by SignalReportStateRequestSerializer — only the
 * fields it declares (state, dismissal_reason, dismissal_note, snooze_for) are read,
 * and only snooze_for is ever forwarded to transition_to. Any other key is ignored,
 * so internal transition_to kwargs (reset_weight, error, ...) can't be injected.
 *
 * Body: {
 *     "state": "suppressed" | "potential",
 *     # Optional dismissal feedback (honored when state == "suppressed" or "potential"):
 *     "dismissal_reason": "<canonical reason code, see SIGNAL_REPORT_DISMISSAL_REASON_CHOICES>",
 *     "dismissal_note": "free-form text",
 *     # Optional, only honored for state == "potential":
 *     "snooze_for": <number of additional signals before re-promotion>,
 * }
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

export const getSignalsReportArtefactsListUrl = (
    projectId: string,
    reportId: string,
    params?: SignalsReportArtefactsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/reports/${reportId}/artefacts/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/reports/${reportId}/artefacts/`
}

/**
 * List every artefact on a report — the full work log: signal findings (the evidence behind the report), status judgments (safety / actionability / priority, repo selection, suggested reviewers — the newest row of each status type is canonical), and log entries (code references, commits, task runs, notes). `suggested_reviewers` content is enriched with PostHog user info at read time.
 * @summary List a report's artefacts
 */
export const signalsReportArtefactsList = async (
    projectId: string,
    reportId: string,
    params?: SignalsReportArtefactsListParams,
    options?: RequestInit
): Promise<PaginatedSignalReportArtefactListApi> => {
    return apiMutator<PaginatedSignalReportArtefactListApi>(
        getSignalsReportArtefactsListUrl(projectId, reportId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getSignalsReportArtefactsCreateUrl = (projectId: string, reportId: string) => {
    return `/api/projects/${projectId}/signals/reports/${reportId}/artefacts/`
}

/**
 * Append an artefact to a report (see artefact_type for the writable types). Everything is append-only: log entries (code reference, commit, task run, note) accumulate, while status types (safety / actionability / priority judgments, repo selection, suggested reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status. Content is validated against the type's schema.
 * @summary Append an artefact to a report
 */
export const signalsReportArtefactsCreate = async (
    projectId: string,
    reportId: string,
    signalReportArtefactLogCreateApi: SignalReportArtefactLogCreateApi,
    options?: RequestInit
): Promise<SignalReportArtefactWriteResponseApi> => {
    return apiMutator<SignalReportArtefactWriteResponseApi>(getSignalsReportArtefactsCreateUrl(projectId, reportId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalReportArtefactLogCreateApi),
    })
}

export const getSignalsReportArtefactsRetrieveUrl = (projectId: string, reportId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${reportId}/artefacts/${id}/`
}

/**
 * Get one artefact by id, content parsed (and reviewers enriched) the same way as the list.
 * @summary Get a single artefact
 */
export const signalsReportArtefactsRetrieve = async (
    projectId: string,
    reportId: string,
    id: string,
    options?: RequestInit
): Promise<SignalReportArtefactApi> => {
    return apiMutator<SignalReportArtefactApi>(getSignalsReportArtefactsRetrieveUrl(projectId, reportId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsReportArtefactsPartialUpdateUrl = (projectId: string, reportId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${reportId}/artefacts/${id}/`
}

/**
 * Replace the content of an existing artefact, addressed by id. The new content is validated against the artefact's type schema. Editing the latest row of a status type changes the report's canonical status (latest-wins); to re-assess while keeping history, append a new artefact instead. Attribution is creation-time only — edits don't reassign it.
 * @summary Replace an artefact's content
 */
export const signalsReportArtefactsPartialUpdate = async (
    projectId: string,
    reportId: string,
    id: string,
    patchedSignalReportArtefactLogUpdateApi?: PatchedSignalReportArtefactLogUpdateApi,
    options?: RequestInit
): Promise<SignalReportArtefactWriteResponseApi> => {
    return apiMutator<SignalReportArtefactWriteResponseApi>(
        getSignalsReportArtefactsPartialUpdateUrl(projectId, reportId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedSignalReportArtefactLogUpdateApi),
        }
    )
}

export const getSignalsReportArtefactsDestroyUrl = (projectId: string, reportId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${reportId}/artefacts/${id}/`
}

/**
 * Delete an artefact, addressed by id. Deleting the latest row of a status type reverts the report's canonical status to the previous version (latest-wins over what remains).
 * @summary Delete an artefact
 */
export const signalsReportArtefactsDestroy = async (
    projectId: string,
    reportId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSignalsReportArtefactsDestroyUrl(projectId, reportId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getSignalsReportArtefactsDiffUrl = (projectId: string, reportId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${reportId}/artefacts/${id}/diff/`
}

/**
 * Fetch the unified diff of a `commit` artefact's branch against the repository default branch via the team's GitHub integration — using the branch's current tip so the diff reflects the latest state of the work, not just the single recorded commit.
 * @summary Fetch the diff for a commit artefact
 */
export const signalsReportArtefactsDiff = async (
    projectId: string,
    reportId: string,
    id: string,
    options?: RequestInit
): Promise<CommitDiffResponseApi> => {
    return apiMutator<CommitDiffResponseApi>(getSignalsReportArtefactsDiffUrl(projectId, reportId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsReportsBulkStateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/reports/bulk-state/`
}

/**
 * Transition many reports to a new state in one call.
 *
 * Each id is processed independently: a report whose transition isn't allowed from its
 * current status is reported as `skipped` (a 409 on the single-report endpoint) and the
 * rest still go through. Returns one result per requested id (in request order, after
 * de-duplication) plus per-outcome counts. The whole call is 200 even on partial failure —
 * inspect `results` / the counts to see what happened.
 */
export const signalsReportsBulkStateCreate = async (
    projectId: string,
    signalReportBulkStateRequestApi: SignalReportBulkStateRequestApi,
    options?: RequestInit
): Promise<SignalReportBulkStateResponseApi> => {
    return apiMutator<SignalReportBulkStateResponseApi>(getSignalsReportsBulkStateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalReportBulkStateRequestApi),
    })
}

export const getSignalsScoutConfigListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/configs/`
}

/**
 * List the per-(team, skill) scout configs for this project — schedule (`run_interval_minutes`), `enabled`, and `emit` posture per scout. A freshly authored scout skill appears here once its config is registered, either explicitly via create or by the coordinator's next tick.
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

export const getSignalsScoutConfigCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/configs/`
}

/**
 * Register the config for a `signals-scout-*` skill immediately, without waiting for the coordinator to auto-register it — optionally setting `run_interval_minutes`, `enabled`, and `emit` in the same call. The skill must already exist on this project. Upsert: if a config already exists for the skill, the provided fields are applied to it.
 * @summary Create a scout config
 */
export const signalsScoutConfigCreate = async (
    projectId: string,
    signalScoutConfigCreateApi: SignalScoutConfigCreateApi,
    options?: RequestInit
): Promise<SignalScoutConfigApi> => {
    return apiMutator<SignalScoutConfigApi>(getSignalsScoutConfigCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(signalScoutConfigCreateApi),
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

export const getSignalsScoutConfigDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/scout/configs/${id}/`
}

/**
 * Delete one scout config by its `id`, removing the per-(team, skill) schedule/emit row outright. The point is cleaning up an orphaned config whose `signals-scout-*` skill was archived or deleted — it lingers in `list` with an empty `description`, never runs (the coordinator skips it and the skill can't load), but can't otherwise be removed over the API. Deletion is activity-logged. Note: if the skill still exists, the coordinator re-creates a default-schedule config on its next tick — to retire a live scout, archive its skill (or set `enabled=false` to make it inert) rather than deleting the config.
 * @summary Delete a scout config
 */
export const signalsScoutConfigDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSignalsScoutConfigDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getSignalsScoutConfigRunUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/scout/configs/${id}/run/`
}

/**
 * Dispatch one on-demand run of this scout immediately, regardless of its schedule. Useful to test a scout right after authoring it, or to refresh its findings on demand. The run executes asynchronously on the worker and inherits every guard the scheduled path has: it is forbidden if scouts are not enabled for the project (403), and skipped if the project is over its Signals credits quota or daily run budget (429) or a run for this scout is already in progress (409). A manual run counts against the same daily run budget as scheduled runs, so repeated manual runs of the same scout can exhaust the project's daily allowance. A manual run does not change the scout's schedule or `last_run_at`. A disabled scout can still be run this way (to test before enabling). Returns immediately with the workflow id — poll the scout's runs for the result.
 * @summary Run a scout now
 */
export const signalsScoutConfigRun = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SignalScoutManualRunApi> => {
    return apiMutator<SignalScoutManualRunApi>(getSignalsScoutConfigRunUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getSignalsScoutConfigSyncUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/configs/sync/`
}

/**
 * Materialize the scout fleet for this project on demand (idempotent): seed the canonical `signals-scout-*` skills, create a default-schedule config for any scout lacking one, and return all scout configs. Normally the Temporal coordinator does this on its next tick; this action exists so setup flows (e.g. the wizard's self-driving program) can hand the user a tunable fleet immediately.
 * @summary Sync scout configs
 */
export const signalsScoutConfigSync = async (
    projectId: string,
    options?: RequestInit
): Promise<SignalScoutConfigApi[]> => {
    return apiMutator<SignalScoutConfigApi[]>(getSignalsScoutConfigSyncUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getSignalsScoutMembersListUrl = (projectId: string, params?: SignalsScoutMembersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/scout/members/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/scout/members/`
}

/**
 * Return the people who can review work on this project — one row per member with access to it, each with their `user_uuid`, `email`, `first_name`/`last_name`, and resolved GitHub `login` (null when they have no linked GitHub identity). The cold-start reviewer-routing path: when a finding's owner can't be read off a fetched entity's `created_by` and there's no cached `reviewer:<area>` memory or inbox precedent, list members, match the owner by email/name, then put their resolved `github_login` in `suggested_reviewers` on `emit-report` / `edit-report`. Pass `search` to narrow a large roster; the result is capped at 200. Strictly team-scoped.
 * @summary List project members for reviewer routing
 */
export const signalsScoutMembersList = async (
    projectId: string,
    params?: SignalsScoutMembersListParams,
    options?: RequestInit
): Promise<ScoutMemberApi[]> => {
    return apiMutator<ScoutMemberApi[]>(getSignalsScoutMembersListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutMetadataGetUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/metadata/current/`
}

/**
 * Return the project's scout metadata: whether it is enrolled, the current announcement banner (e.g. an alpha run-limit notice, or null when unset), and the enforced run limits with current usage. Limits reflect what the coordinator actually applies at dispatch, so a user can see the real throttle rather than what they assume they set. All values come from the `signals-scout` flag payload, so the banner and caps can change with no deploy.
 * @summary Get scout metadata
 */
export const signalsScoutMetadataGet = async (projectId: string, options?: RequestInit): Promise<ScoutMetadataApi> => {
    return apiMutator<ScoutMetadataApi>(getSignalsScoutMetadataGetUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutProjectProfileGetUrl = (
    projectId: string,
    params?: SignalsScoutProjectProfileGetParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/scout/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/scout/runs/`
}

/**
 * Return the most recent `SignalScoutRun` summaries for this project, newest first. Used by the headless scout to dedupe against work other runs already covered. ILIKE matches on `summary`. `date_from` / `date_to` are a half-open window on `created_at` (`>= date_from`, `< date_to`); pass `date_to` on subsequent calls to walk past the 100-row cap. Pass `emitted=true` to see only runs that surfaced at least one finding. Pass `skill_name` (optionally with `skill_version`) to scope to a single scout. Results capped at 100.
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

export const getSignalsScoutRunsRetrieveUrl = (projectId: string, runId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${runId}/`
}

/**
 * Return the full `SignalScoutRun` row. Status, timing, and error flow from the linked `tasks.TaskRun`. Strictly team-scoped — a UUID belonging to another team returns 404.
 * @summary Get a run by ID
 */
export const signalsScoutRunsRetrieve = async (
    projectId: string,
    runId: string,
    options?: RequestInit
): Promise<SignalScoutRunDetailApi> => {
    return apiMutator<SignalScoutRunDetailApi>(getSignalsScoutRunsRetrieveUrl(projectId, runId), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutEditReportUrl = (projectId: string, runId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${runId}/edit-report/`
}

/**
 * Rewrite a report's title/summary, append a note, and/or set its suggested reviewers. Can target ANY of the project's inbox reports, not just scout-authored ones — so the edit is attributed to this scout. Setting reviewers is how you rescue a report that surfaced routed to no one: it replaces the reviewer list and re-runs autostart, so a report missing a qualifying reviewer can open a draft PR. Title/summary edits are best-effort: the pipeline may later re-research them.
 * @summary Edit an existing report for a run
 */
export const signalsScoutEditReport = async (
    projectId: string,
    runId: string,
    editReportRequestApi: EditReportRequestApi,
    options?: RequestInit
): Promise<EditReportResponseApi> => {
    return apiMutator<EditReportResponseApi>(getSignalsScoutEditReportUrl(projectId, runId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(editReportRequestApi),
    })
}

export const getSignalsScoutRunsEmissionsUrl = (projectId: string, runId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${runId}/emissions/`
}

/**
 * Return the findings a `SignalScoutRun` emitted to the inbox, newest first — one row per emit with its `description` (the finding text as surfaced), `weight`, `confidence`, `severity`, and the deterministic `source_id` that joins back to the underlying signal. Lets a team and its agents see *what* a run surfaced without parsing `emitted_finding_ids` or scanning the signal store. Strictly team-scoped — a run UUID belonging to another team returns 404.
 * @summary List a run's emitted findings
 */
export const signalsScoutRunsEmissions = async (
    projectId: string,
    runId: string,
    options?: RequestInit
): Promise<SignalScoutEmissionApi[]> => {
    return apiMutator<SignalScoutEmissionApi[]>(getSignalsScoutRunsEmissionsUrl(projectId, runId), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutRunsEmissionReportsUrl = (projectId: string, runId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${runId}/emissions/reports/`
}

/**
 * Best-effort reverse of the report -> signals link. For each finding the run emitted, resolve the inbox `SignalReport` (if any) its underlying signal grouped into by walking the deterministic `source_id` back through the signal store. `report` is null when the finding hasn't grouped into a report yet, was de-duplicated away, or its signal was deleted. Lets the scout UI surface which inbox report a finding contributed to — the reverse of the report's evidence list. Strictly team-scoped — a run UUID belonging to another team returns 404.
 * @summary List the inbox reports a run's findings linked to
 */
export const signalsScoutRunsEmissionReports = async (
    projectId: string,
    runId: string,
    options?: RequestInit
): Promise<ScoutEmissionReportLinkApi[]> => {
    return apiMutator<ScoutEmissionReportLinkApi[]>(getSignalsScoutRunsEmissionReportsUrl(projectId, runId), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutEmitReportUrl = (projectId: string, runId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${runId}/emit-report/`
}

/**
 * The second emit channel: author a complete `SignalReport` directly instead of emitting a weak signal. The report passes the safety judge, then surfaces at the status the scout's `actionability` call implies (or is suppressed). Backing `evidence` is written as bound signals so the report behaves like a pipeline report. NOT idempotent — a retry authors a second report; use `reports` to find a prior report and `edit-report` to update it instead.
 * @summary Author a full report for a run
 */
export const signalsScoutEmitReport = async (
    projectId: string,
    runId: string,
    emitReportRequestApi: EmitReportRequestApi,
    options?: RequestInit
): Promise<EmitReportResponseApi> => {
    return apiMutator<EmitReportResponseApi>(getSignalsScoutEmitReportUrl(projectId, runId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(emitReportRequestApi),
    })
}

export const getSignalsScoutEmitSignalUrl = (projectId: string, runId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${runId}/emit-signal/`
}

/**
 * Fire `emit_signal` with `source_product = signals_scout`. The `finding_id` is baked into the deterministic `Signal.source_id = run:<id>:finding:<id>` for traceability, but this is NOT idempotent — a second call with the same `finding_id` emits a second signal, so do not retry an emit that may have already succeeded.
 * @summary Emit a finding for a run
 */
export const signalsScoutEmitSignal = async (
    projectId: string,
    runId: string,
    emitFindingRequestApi: EmitFindingRequestApi,
    options?: RequestInit
): Promise<EmitFindingResponseApi> => {
    return apiMutator<EmitFindingResponseApi>(getSignalsScoutEmitSignalUrl(projectId, runId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(emitFindingRequestApi),
    })
}

export const getSignalsScoutNotifyUrl = (projectId: string, runId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/${runId}/notify/`
}

/**
 * Deliver a finding summary to this scout's configured Slack channel, tagging the account owner when `owner_email` resolves to a Slack user. The channel always comes from the scout config's `delivery_config` — never from the request. Capped at 5 alerts per run. File (or edit) the inbox report first and pass its `report_id` so the alert links back. Delivery errors are terminal for the run — note them in your run summary and do not retry.
 * @summary Send a Slack alert for a confirmed finding
 */
export const signalsScoutNotify = async (
    projectId: string,
    runId: string,
    scoutNotifyRequestApi: ScoutNotifyRequestApi,
    options?: RequestInit
): Promise<ScoutNotifyResponseApi> => {
    return apiMutator<ScoutNotifyResponseApi>(getSignalsScoutNotifyUrl(projectId, runId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scoutNotifyRequestApi),
    })
}

export const getSignalsScoutRunsEmissionsBatchUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/emissions/batch/`
}

/**
 * Batched form of the per-run emissions endpoint: return the findings every requested `SignalScoutRun` emitted, flattened newest-first, in a single request. Each row carries its `run_id`, so the caller can regroup by run. The findings UI uses this to load the whole recent window in one round-trip instead of one request per run. Strictly team-scoped — run ids belonging to another team contribute no rows (no per-run 404; one stale id never fails the batch).
 * @summary List emitted findings for many runs at once
 */
export const signalsScoutRunsEmissionsBatch = async (
    projectId: string,
    scoutRunIdsBatchRequestApi: ScoutRunIdsBatchRequestApi,
    options?: RequestInit
): Promise<SignalScoutEmissionApi[]> => {
    return apiMutator<SignalScoutEmissionApi[]>(getSignalsScoutRunsEmissionsBatchUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scoutRunIdsBatchRequestApi),
    })
}

export const getSignalsScoutRunsRecentEmissionsUrl = (
    projectId: string,
    params?: SignalsScoutRunsRecentEmissionsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/scout/runs/emissions/recent/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/scout/runs/emissions/recent/`
}

/**
 * Return the team's recently emitted scout findings across *every* run, newest first — the cross-run counterpart to the per-run `emissions` action. Each row carries its `run_id`, so you can regroup by run without first listing runs and fanning out one `emissions` call each. Pass `skill_name` to scope to a single scout, and `date_from` / `date_to` (a half-open window on `emitted_at`) to bound or paginate — set `date_to` to the oldest emission's `emitted_at` to walk back past the limit. Pure Postgres, no ClickHouse round-trip. Capped at 200 rows (default 50).
 * @summary List recent emitted findings across all runs
 */
export const signalsScoutRunsRecentEmissions = async (
    projectId: string,
    params?: SignalsScoutRunsRecentEmissionsParams,
    options?: RequestInit
): Promise<SignalScoutEmissionApi[]> => {
    return apiMutator<SignalScoutEmissionApi[]>(getSignalsScoutRunsRecentEmissionsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutRunsEmissionReportsBatchUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/emissions/reports/batch/`
}

/**
 * Batched form of the per-run emission-reports endpoint. For every finding the requested runs emitted, resolve the inbox `SignalReport` (if any) its signal grouped into — all in a single ClickHouse round-trip rather than one query per run, which is what made the findings page slow to open. `report` is null when a finding hasn't grouped yet, was de-duplicated, or its signal was deleted. Strictly team-scoped — run ids belonging to another team contribute no rows.
 * @summary List the inbox reports many runs' findings linked to
 */
export const signalsScoutRunsEmissionReportsBatch = async (
    projectId: string,
    scoutRunIdsBatchRequestApi: ScoutRunIdsBatchRequestApi,
    options?: RequestInit
): Promise<ScoutEmissionReportLinkApi[]> => {
    return apiMutator<ScoutEmissionReportLinkApi[]>(getSignalsScoutRunsEmissionReportsBatchUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scoutRunIdsBatchRequestApi),
    })
}

export const getSignalsScoutRunsFindingsSummaryUrl = (
    projectId: string,
    params?: SignalsScoutRunsFindingsSummaryParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/scout/runs/findings/summary/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/scout/runs/findings/summary/`
}

/**
 * Return a cheap fleet-wide tally of the findings the scout troop emitted in the recent window — the total count, the number of distinct scouts behind them, and the latest emission time. Backs the 'Scout findings' callout so it renders from one query instead of the client paging through the whole runs window. Counts only runs that emitted at least one finding (`emitted_count > 0`) within the last `window_hours` (default 72), capped to the most recent 120 emitted runs so the count matches what the findings list renders. Strictly team-scoped.
 * @summary Summarise recently emitted findings across the fleet
 */
export const signalsScoutRunsFindingsSummary = async (
    projectId: string,
    params?: SignalsScoutRunsFindingsSummaryParams,
    options?: RequestInit
): Promise<FleetFindingsSummaryApi> => {
    return apiMutator<FleetFindingsSummaryApi>(getSignalsScoutRunsFindingsSummaryUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSignalsScoutScratchpadSearchUrl = (projectId: string, params?: SignalsScoutScratchpadSearchParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/signals/scout/scratchpad/?${stringifiedParams}`
        : `/api/projects/${projectId}/signals/scout/scratchpad/`
}

/**
 * Return `SignalScratchpad` entries for this project, newest-first. ILIKE matches on `content` and `key`. `date_from` / `date_to` are a half-open window on `updated_at` (`>= date_from`, `< date_to`); pass `date_to` (the `updated_at` of the oldest entry seen) on subsequent calls to walk past the cap. Pass `keys_only=true` to scan keys without pulling entry bodies, or `content_max_chars` to cap each `content` to a preview — both keep a wide orientation scan from returning every entry's full prose. Results capped at 500.
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
 *
 * GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
 * POST   /api/users/<id>/signal_autonomy/ → create or update
 * DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
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
 *
 * GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
 * POST   /api/users/<id>/signal_autonomy/ → create or update
 * DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
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
 *
 * GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
 * POST   /api/users/<id>/signal_autonomy/ → create or update
 * DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const usersSignalAutonomyDestroy = async (userId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersSignalAutonomyDestroyUrl(userId), {
        ...options,
        method: 'DELETE',
    })
}
