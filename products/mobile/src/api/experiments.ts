import type {
    ActiveRecalculationRunApi,
    ArchiveExperimentApi,
    EndExperimentApi,
    ExperimentBasicApi,
    ExperimentMetricsRecalculationJobApi,
    ExperimentMetricsRecalculationRunApi,
    ExperimentsListParams,
    ExperimentsListStatus,
    ExperimentApi as GeneratedExperimentApi,
    ExperimentHealthApi as GeneratedExperimentHealthApi,
    ExperimentFlagCleanupTargetApi as GeneratedFlagCleanupTargetApi,
    MetricRecalculationResultApi,
    PaginatedExperimentBasicListApi,
    PatchedExperimentWriteApi,
    RecalculateMetricsRequestApi,
    ResultSourceEnumApi,
    RunningTimeTargetApi,
    ShipVariantApi,
} from '../../../experiments/frontend/generated/api.schemas'

import { ApiError, apiJson, scopedPath } from './client'
import { runQuery } from './query'
import { type ProjectScope, scopeKey } from './reports'

// Shapes follow `products/experiments/backend/presentation/views.py` (`EnterpriseExperimentsViewSet`) and the
// serializers next to it. Every read needs `experiment:read`; launch, end, ship, pause, resume, archive, the
// conclusion PATCH and `metrics_recalculation` need `experiment:write`.
//
// The list filter `status=` accepts `draft`, `running`, `paused`, `exposure_frozen`, `stopped`, `complete` (an alias
// of `stopped`) and `all` (`ExperimentQueryStatus` in `experiment_service.py`); anything else is ignored. `running`,
// `paused` and `exposure_frozen` are mutually exclusive, so the Running segment reads all three. The list also takes
// `search` (name or flag key, case-insensitive), `order` (an allowlist that includes `-start_date`, `-end_date` and
// `-created_at`) and `archived` (false unless sent).
//
// Scopes this module does not request, so the callers must never send them: `disable_feature_flag` on archive needs
// `feature_flag:write`, and `set_repository_as_team_default` on end and ship needs `project:write` plus project admin.
// `open_cleanup_pr` needs `task:write`, which the app already has for chats.

/** `ExperimentBasicSerializer`, the list endpoint's row. */
export type ExperimentListItemApi = ExperimentBasicApi

/** `ExperimentSerializer`, the detail and every lifecycle action's response. Generated, not hand-typed. */
export type ExperimentApi = GeneratedExperimentApi

export type ExperimentConclusionApi = NonNullable<ExperimentApi['conclusion']>
export type ExperimentStatusApi = ExperimentApi['status']

/** `ExperimentStatsBaseValidated` in `posthog/schema.py`: the control row of a result. */
export interface ExperimentStatsApi {
    key: string
    number_of_samples: number
    sum: number
    sum_squares: number
    /** Ratio metrics divide `sum` by this instead of `number_of_samples`. */
    denominator_sum?: number | null
    step_counts?: number[] | null
    /** Quantile metrics: the quantile's value first, then bounds. */
    quantile_grid?: number[] | null
    /** `not-enough-exposures` and `not-enough-metric-data` mean the result is too early to read. */
    validation_failures?: string[] | null
}

/**
 * `ExperimentVariantResultBayesian` or `ExperimentVariantResultFrequentist`. The intervals are on the relative change
 * against the control, as fractions (0.12 is +12%).
 */
export interface ExperimentVariantResultApi extends ExperimentStatsApi {
    method?: 'bayesian' | 'frequentist'
    significant?: boolean | null
    chance_to_win?: number | null
    credible_interval?: [number, number] | null
    p_value?: number | null
    confidence_interval?: [number, number] | null
}

/** `ExperimentQueryResponse`: one metric's result as the recalculation stores it. */
export interface ExperimentQueryResultApi {
    kind?: 'ExperimentQuery'
    baseline?: ExperimentStatsApi | null
    variant_results?: ExperimentVariantResultApi[] | null
}

/** `MetricRecalculationResultSerializer` with the result typed. */
export interface ExperimentMetricResultRowApi extends Omit<MetricRecalculationResultApi, 'result'> {
    readonly result: ExperimentQueryResultApi | null
}

/**
 * `GET metrics_recalculation/latest/` and `GET metrics_recalculation/{run}/`. Only `latest` carries `active_run`,
 * `result_source` and `exceeds_recalculation_age_limit`.
 */
export interface ExperimentResultsRunApi extends Omit<ExperimentMetricsRecalculationRunApi, 'results'> {
    readonly results: readonly ExperimentMetricResultRowApi[]
    readonly active_run?: ActiveRecalculationRunApi | null
    readonly result_source?: ResultSourceEnumApi
    readonly exceeds_recalculation_age_limit?: boolean
}

/** `POST metrics_recalculation/`: the queued or already active job. It carries no results. */
export type ExperimentRecalculationJobApi = ExperimentMetricsRecalculationJobApi

export type ExperimentRunningTimeTargetApi = RunningTimeTargetApi
export type ExperimentHealthApi = GeneratedExperimentHealthApi
export type ExperimentFlagCleanupTargetApi = GeneratedFlagCleanupTargetApi

/** `ExperimentExposureTimeSeries` in `posthog/schema.py`. */
export interface ExperimentExposureSeriesApi {
    variant: string
    days: string[]
    exposure_counts: number[]
}

/** `ExperimentExposureHealthFinding`, the fields the app reads. */
export interface ExperimentExposureFindingApi {
    code: string
    detail: string
    severity?: string
    title?: string
}

/** `ExperimentExposureQueryResponse`, the fields the app reads. */
export interface ExperimentExposureResponseApi {
    timeseries: ExperimentExposureSeriesApi[]
    total_exposures: Record<string, number>
    /**
     * `expected` holds each variant's expected exposure count from the split, scaled to the observed total
     * (`health/checks/srm.py`).
     */
    sample_ratio_mismatch?: { expected: Record<string, number>; p_value: number } | null
    health_findings?: ExperimentExposureFindingApi[] | null
    date_range?: { date_from?: string | null; date_to?: string | null }
}

export type ExperimentListSegment = 'running' | 'complete' | 'draft'

export const EXPERIMENTS_PAGE_SIZE = 20

/** The `status=` values each segment reads. Paused and frozen experiments are still running to a reader. */
export const SEGMENT_STATUSES: Record<ExperimentListSegment, readonly ExperimentsListStatus[]> = {
    running: ['running', 'paused', 'exposure_frozen'],
    complete: ['stopped'],
    draft: ['draft'],
}

/** The server order, so a page holds the rows the segment's own order shows first. */
export const SEGMENT_ORDER: Record<ExperimentListSegment, string> = {
    running: '-start_date',
    complete: '-end_date',
    draft: '-created_at',
}

export interface ExperimentsListInput {
    status: ExperimentListSegment
    /** Trimmed text. Empty or missing sends no `search`. */
    search?: string
}

export interface ExperimentsPage {
    results: ExperimentListItemApi[]
    hasMore: boolean
    nextOffset: number
}

export function experimentsListParams(
    input: ExperimentsListInput,
    status: ExperimentsListStatus,
    offset: number
): ExperimentsListParams {
    const search = input.search?.trim()
    return {
        status,
        order: SEGMENT_ORDER[input.status],
        limit: EXPERIMENTS_PAGE_SIZE,
        offset,
        ...(search ? { search } : {}),
    }
}

/**
 * One page of a segment. A segment with several statuses reads each at the same offset and merges them, so a later
 * page continues every status at once.
 */
export async function fetchExperiments(
    scope: ProjectScope | null,
    input: ExperimentsListInput,
    signal?: AbortSignal,
    offset = 0
): Promise<ExperimentsPage> {
    const pages = await Promise.all(
        SEGMENT_STATUSES[input.status].map((status) =>
            apiJson<PaginatedExperimentBasicListApi>(scopedPath(scope, 'experiments/'), {
                query: { ...experimentsListParams(input, status, offset) },
                signal,
            })
        )
    )
    const seen = new Set<number>()
    const results: ExperimentListItemApi[] = []
    for (const page of pages) {
        for (const row of page.results) {
            if (!seen.has(row.id)) {
                seen.add(row.id)
                results.push(row)
            }
        }
    }
    return {
        results,
        hasMore: pages.some((page) => Boolean(page.next)),
        nextOffset: offset + EXPERIMENTS_PAGE_SIZE,
    }
}

/** Every path names the screen's project, so a read started before a project switch never lands in the new one. */
function experimentPath(scope: ProjectScope | null, id: string | number, suffix = ''): string {
    return scopedPath(scope, `experiments/${encodeURIComponent(String(id))}/${suffix}`)
}

export function fetchExperiment(
    scope: ProjectScope | null,
    id: string | number,
    signal?: AbortSignal
): Promise<ExperimentApi> {
    return apiJson<ExperimentApi>(experimentPath(scope, id), { signal })
}

/** The stored results: the newest finished run or the daily fallback. Null when the experiment has none yet (404). */
export async function fetchLatestResults(
    scope: ProjectScope | null,
    id: string | number,
    signal?: AbortSignal
): Promise<ExperimentResultsRunApi | null> {
    try {
        return await apiJson<ExperimentResultsRunApi>(experimentPath(scope, id, 'metrics_recalculation/latest/'), {
            signal,
        })
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
            return null
        }
        throw error
    }
}

export function fetchResultsRun(
    scope: ProjectScope | null,
    id: string | number,
    runId: string,
    signal?: AbortSignal
): Promise<ExperimentResultsRunApi> {
    return apiJson<ExperimentResultsRunApi>(
        experimentPath(scope, id, `metrics_recalculation/${encodeURIComponent(runId)}/`),
        {
            signal,
        }
    )
}

export interface RecalculationStart {
    /** Null when the server refused a manual run inside its five-minute window. */
    run: ExperimentRecalculationJobApi | null
    /** The `Retry-After` wait of that refusal, or null. */
    retryAfterMs: number | null
}

/** `POST metrics_recalculation/`. 201 starts a run, 200 returns the active one, 429 is the five-minute window. */
export async function startRecalculation(scope: ProjectScope | null, id: string | number): Promise<RecalculationStart> {
    try {
        const run = await apiJson<ExperimentRecalculationJobApi>(experimentPath(scope, id, 'metrics_recalculation/'), {
            method: 'POST',
            json: { trigger: 'manual' } satisfies RecalculateMetricsRequestApi,
        })
        return { run, retryAfterMs: null }
    } catch (error) {
        if (error instanceof ApiError && error.status === 429) {
            return { run: null, retryAfterMs: (error.retryAfterSeconds ?? 0) * 1000 }
        }
        throw error
    }
}

export function fetchRunningTimeTarget(
    scope: ProjectScope | null,
    id: string | number,
    signal?: AbortSignal
): Promise<ExperimentRunningTimeTargetApi> {
    return apiJson<ExperimentRunningTimeTargetApi>(experimentPath(scope, id, 'running_time_target/'), { signal })
}

export function fetchHealth(
    scope: ProjectScope | null,
    id: string | number,
    signal?: AbortSignal
): Promise<ExperimentHealthApi> {
    return apiJson<ExperimentHealthApi>(experimentPath(scope, id, 'health/'), { signal })
}

/**
 * The query the web's `experimentLogic` sends for the exposures card. `asOf` is the stored results' `query_to`, so the
 * exposures end where the results window ends; without it they run to now.
 */
export function exposureQuery(experiment: ExperimentApi, asOf?: string | null): Record<string, unknown> {
    return {
        kind: 'ExperimentExposureQuery',
        experiment_id: experiment.id,
        experiment_name: experiment.name,
        exposure_criteria: experiment.exposure_criteria,
        feature_flag: experiment.feature_flag,
        start_date: experiment.start_date,
        end_date: experiment.end_date,
        holdout: experiment.holdout,
        ...(asOf ? { as_of: asOf } : {}),
    }
}

/** `POST query/` with `ExperimentExposureQuery`. Needs `query:read` only. */
export async function fetchExposures(
    scope: ProjectScope | null,
    experiment: ExperimentApi,
    signal?: AbortSignal,
    asOf?: string | null
): Promise<ExperimentExposureResponseApi> {
    return (await runQuery(exposureQuery(experiment, asOf), { signal, scope })) as ExperimentExposureResponseApi
}

export function fetchFlagCleanupTarget(
    scope: ProjectScope | null,
    id: string | number,
    signal?: AbortSignal
): Promise<ExperimentFlagCleanupTargetApi> {
    return apiJson<ExperimentFlagCleanupTargetApi>(experimentPath(scope, id, 'flag_cleanup_target/'), { signal })
}

export function launchExperiment(scope: ProjectScope | null, id: string | number): Promise<ExperimentApi> {
    return apiJson<ExperimentApi>(experimentPath(scope, id, 'launch/'), { method: 'POST' })
}

/** The finish sheet's fields. The app never sends `set_repository_as_team_default` (see the header). */
export type EndExperimentBody = Omit<EndExperimentApi, 'set_repository_as_team_default'>
export type ShipVariantBody = Omit<ShipVariantApi, 'set_repository_as_team_default'>

/** `POST end/`: ends without touching the flag. */
export function endExperiment(
    scope: ProjectScope | null,
    id: string | number,
    body: EndExperimentBody
): Promise<ExperimentApi> {
    return apiJson<ExperimentApi>(experimentPath(scope, id, 'end/'), { method: 'POST', json: body })
}

export type ShipResult =
    | { status: 'shipped'; experiment: ExperimentApi }
    /**
     * An approval policy holds the flag change. The experiment stays running until a reviewer approves. `code` is
     * `change_request_pending` when a request for this change already existed, else `approval_required`.
     */
    | { status: 'needs_approval'; changeRequestId: string; code: string | null }

/** `POST ship_variant/`: rewrites the flag to the variant and ends a running experiment. */
export async function shipVariant(
    scope: ProjectScope | null,
    id: string | number,
    body: ShipVariantBody
): Promise<ShipResult> {
    try {
        const experiment = await apiJson<ExperimentApi>(experimentPath(scope, id, 'ship_variant/'), {
            method: 'POST',
            json: body,
        })
        return { status: 'shipped', experiment }
    } catch (error) {
        const changeRequestId = approvalChangeRequestId(error)
        if (changeRequestId) {
            return {
                status: 'needs_approval',
                changeRequestId,
                code: error instanceof ApiError ? (error.code ?? null) : null,
            }
        }
        throw error
    }
}

/** The change request id of the 409 `ApprovalHandlingMixin` answers with, or null for any other error. */
export function approvalChangeRequestId(error: unknown): string | null {
    if (!(error instanceof ApiError) || error.status !== 409) {
        return null
    }
    const body = error.body as { change_request_id?: unknown } | null | undefined
    return typeof body?.change_request_id === 'string' ? body.change_request_id : null
}

export function pauseExperiment(scope: ProjectScope | null, id: string | number): Promise<ExperimentApi> {
    return apiJson<ExperimentApi>(experimentPath(scope, id, 'pause/'), { method: 'POST' })
}

export function resumeExperiment(scope: ProjectScope | null, id: string | number): Promise<ExperimentApi> {
    return apiJson<ExperimentApi>(experimentPath(scope, id, 'resume/'), { method: 'POST' })
}

/** Archives an ended experiment and leaves its flag alone. 400 when the experiment has not ended. */
export function archiveExperiment(scope: ProjectScope | null, id: string | number): Promise<ExperimentApi> {
    return apiJson<ExperimentApi>(experimentPath(scope, id, 'archive/'), {
        method: 'POST',
        json: {} satisfies ArchiveExperimentApi,
    })
}

export type ExperimentPatch = Pick<PatchedExperimentWriteApi, 'conclusion' | 'conclusion_comment'>

/** Sends no `version`, so the server skips its concurrent-edit check for these two fields. */
export function updateExperiment(
    scope: ProjectScope | null,
    id: string | number,
    patch: ExperimentPatch
): Promise<ExperimentApi> {
    return apiJson<ExperimentApi>(experimentPath(scope, id), { method: 'PATCH', json: patch })
}

/** Query keys. Every key carries the host and project so a project switch never shows stale data. */
export const experimentKeys = {
    all: (scope: ProjectScope | null) => ['experiments', ...scopeKey(scope)] as const,
    lists: (scope: ProjectScope | null) => [...experimentKeys.all(scope), 'list'] as const,
    list: (scope: ProjectScope | null, input: ExperimentsListInput) =>
        [...experimentKeys.lists(scope), input.status, input.search?.trim() ?? '', 'pages'] as const,
    experimentAll: (scope: ProjectScope | null, id: string | number) =>
        [...experimentKeys.all(scope), 'experiment', String(id)] as const,
    detail: (scope: ProjectScope | null, id: string | number) =>
        [...experimentKeys.experimentAll(scope, id), 'detail'] as const,
    latest: (scope: ProjectScope | null, id: string | number) =>
        [...experimentKeys.experimentAll(scope, id), 'latest'] as const,
    run: (scope: ProjectScope | null, id: string | number, runId: string) =>
        [...experimentKeys.experimentAll(scope, id), 'run', runId] as const,
    target: (scope: ProjectScope | null, id: string | number) =>
        [...experimentKeys.experimentAll(scope, id), 'target'] as const,
    health: (scope: ProjectScope | null, id: string | number) =>
        [...experimentKeys.experimentAll(scope, id), 'health'] as const,
    /** `asOf` is the `as_of` the query was sent with; leaving it out keys the whole exposures family. */
    exposures: (scope: ProjectScope | null, id: string | number, asOf?: string | null) =>
        asOf === undefined
            ? ([...experimentKeys.experimentAll(scope, id), 'exposures'] as const)
            : ([...experimentKeys.experimentAll(scope, id), 'exposures', asOf ?? 'now'] as const),
    cleanupTarget: (scope: ProjectScope | null, id: string | number) =>
        [...experimentKeys.experimentAll(scope, id), 'cleanup_target'] as const,
}

type WithoutScope<F> = F extends (scope: ProjectScope | null, ...args: infer A) => infer R ? (...args: A) => R : never

/**
 * Every read and write the experiments screens make, bound to one project. Demo mode swaps in `demoExperimentsSource`
 * from `src/demo/experiments.ts` with the same signatures, so the hooks never branch on the mode.
 */
export interface ExperimentsSource {
    fetchExperiments: WithoutScope<typeof fetchExperiments>
    fetchExperiment: WithoutScope<typeof fetchExperiment>
    fetchLatestResults: WithoutScope<typeof fetchLatestResults>
    fetchResultsRun: WithoutScope<typeof fetchResultsRun>
    startRecalculation: WithoutScope<typeof startRecalculation>
    fetchRunningTimeTarget: WithoutScope<typeof fetchRunningTimeTarget>
    fetchHealth: WithoutScope<typeof fetchHealth>
    fetchExposures: WithoutScope<typeof fetchExposures>
    fetchFlagCleanupTarget: WithoutScope<typeof fetchFlagCleanupTarget>
    launchExperiment: WithoutScope<typeof launchExperiment>
    endExperiment: WithoutScope<typeof endExperiment>
    shipVariant: WithoutScope<typeof shipVariant>
    pauseExperiment: WithoutScope<typeof pauseExperiment>
    resumeExperiment: WithoutScope<typeof resumeExperiment>
    archiveExperiment: WithoutScope<typeof archiveExperiment>
    updateExperiment: WithoutScope<typeof updateExperiment>
}

/** The live calls for `scope`, the same project the screen's query keys name. */
export function liveExperimentsSource(scope: ProjectScope | null): ExperimentsSource {
    return {
        fetchExperiments: (...args) => fetchExperiments(scope, ...args),
        fetchExperiment: (...args) => fetchExperiment(scope, ...args),
        fetchLatestResults: (...args) => fetchLatestResults(scope, ...args),
        fetchResultsRun: (...args) => fetchResultsRun(scope, ...args),
        startRecalculation: (...args) => startRecalculation(scope, ...args),
        fetchRunningTimeTarget: (...args) => fetchRunningTimeTarget(scope, ...args),
        fetchHealth: (...args) => fetchHealth(scope, ...args),
        fetchExposures: (...args) => fetchExposures(scope, ...args),
        fetchFlagCleanupTarget: (...args) => fetchFlagCleanupTarget(scope, ...args),
        launchExperiment: (...args) => launchExperiment(scope, ...args),
        endExperiment: (...args) => endExperiment(scope, ...args),
        shipVariant: (...args) => shipVariant(scope, ...args),
        pauseExperiment: (...args) => pauseExperiment(scope, ...args),
        resumeExperiment: (...args) => resumeExperiment(scope, ...args),
        archiveExperiment: (...args) => archiveExperiment(scope, ...args),
        updateExperiment: (...args) => updateExperiment(scope, ...args),
    }
}
