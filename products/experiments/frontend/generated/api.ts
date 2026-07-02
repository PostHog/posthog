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
    ArchiveExperimentApi,
    CopyExperimentToProjectApi,
    CreateFromPromptInputApi,
    EndExperimentApi,
    ExperimentApi,
    ExperimentHoldoutApi,
    ExperimentHoldoutsListParams,
    ExperimentMetricsRecalculationApi,
    ExperimentSavedMetricApi,
    ExperimentSavedMetricsListParams,
    ExperimentsListParams,
    ExperimentsPromptTemplatesRetrieve200Item,
    ExperimentsTimeseriesResultsRetrieveParams,
    PaginatedExperimentBasicListApi,
    PaginatedExperimentHoldoutListApi,
    PaginatedExperimentSavedMetricListApi,
    PatchedExperimentApi,
    PatchedExperimentHoldoutApi,
    PatchedExperimentSavedMetricApi,
    RecalculateMetricsRequestApi,
    RunningTimeCalculationInputApi,
    RunningTimeCalculationResultApi,
    ShipVariantApi,
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

export const getExperimentHoldoutsListUrl = (projectId: string, params?: ExperimentHoldoutsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/experiment_holdouts/?${stringifiedParams}`
        : `/api/projects/${projectId}/experiment_holdouts/`
}

export const experimentHoldoutsList = async (
    projectId: string,
    params?: ExperimentHoldoutsListParams,
    options?: RequestInit
): Promise<PaginatedExperimentHoldoutListApi> => {
    return apiMutator<PaginatedExperimentHoldoutListApi>(getExperimentHoldoutsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentHoldoutsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiment_holdouts/`
}

export const experimentHoldoutsCreate = async (
    projectId: string,
    experimentHoldoutApi: NonReadonly<ExperimentHoldoutApi>,
    options?: RequestInit
): Promise<ExperimentHoldoutApi> => {
    return apiMutator<ExperimentHoldoutApi>(getExperimentHoldoutsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentHoldoutApi),
    })
}

export const getExperimentHoldoutsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_holdouts/${id}/`
}

export const experimentHoldoutsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentHoldoutApi> => {
    return apiMutator<ExperimentHoldoutApi>(getExperimentHoldoutsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentHoldoutsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_holdouts/${id}/`
}

export const experimentHoldoutsUpdate = async (
    projectId: string,
    id: number,
    experimentHoldoutApi: NonReadonly<ExperimentHoldoutApi>,
    options?: RequestInit
): Promise<ExperimentHoldoutApi> => {
    return apiMutator<ExperimentHoldoutApi>(getExperimentHoldoutsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentHoldoutApi),
    })
}

export const getExperimentHoldoutsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_holdouts/${id}/`
}

export const experimentHoldoutsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedExperimentHoldoutApi?: NonReadonly<PatchedExperimentHoldoutApi>,
    options?: RequestInit
): Promise<ExperimentHoldoutApi> => {
    return apiMutator<ExperimentHoldoutApi>(getExperimentHoldoutsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExperimentHoldoutApi),
    })
}

export const getExperimentHoldoutsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_holdouts/${id}/`
}

export const experimentHoldoutsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentHoldoutsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getExperimentSavedMetricsListUrl = (projectId: string, params?: ExperimentSavedMetricsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/experiment_saved_metrics/?${stringifiedParams}`
        : `/api/projects/${projectId}/experiment_saved_metrics/`
}

export const experimentSavedMetricsList = async (
    projectId: string,
    params?: ExperimentSavedMetricsListParams,
    options?: RequestInit
): Promise<PaginatedExperimentSavedMetricListApi> => {
    return apiMutator<PaginatedExperimentSavedMetricListApi>(getExperimentSavedMetricsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentSavedMetricsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiment_saved_metrics/`
}

export const experimentSavedMetricsCreate = async (
    projectId: string,
    experimentSavedMetricApi: NonReadonly<ExperimentSavedMetricApi>,
    options?: RequestInit
): Promise<ExperimentSavedMetricApi> => {
    return apiMutator<ExperimentSavedMetricApi>(getExperimentSavedMetricsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentSavedMetricApi),
    })
}

export const getExperimentSavedMetricsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_saved_metrics/${id}/`
}

export const experimentSavedMetricsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentSavedMetricApi> => {
    return apiMutator<ExperimentSavedMetricApi>(getExperimentSavedMetricsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentSavedMetricsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_saved_metrics/${id}/`
}

export const experimentSavedMetricsUpdate = async (
    projectId: string,
    id: number,
    experimentSavedMetricApi: NonReadonly<ExperimentSavedMetricApi>,
    options?: RequestInit
): Promise<ExperimentSavedMetricApi> => {
    return apiMutator<ExperimentSavedMetricApi>(getExperimentSavedMetricsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentSavedMetricApi),
    })
}

export const getExperimentSavedMetricsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_saved_metrics/${id}/`
}

export const experimentSavedMetricsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedExperimentSavedMetricApi?: NonReadonly<PatchedExperimentSavedMetricApi>,
    options?: RequestInit
): Promise<ExperimentSavedMetricApi> => {
    return apiMutator<ExperimentSavedMetricApi>(getExperimentSavedMetricsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExperimentSavedMetricApi),
    })
}

export const getExperimentSavedMetricsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_saved_metrics/${id}/`
}

export const experimentSavedMetricsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentSavedMetricsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getExperimentsListUrl = (projectId: string, params?: ExperimentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/experiments/?${stringifiedParams}`
        : `/api/projects/${projectId}/experiments/`
}

/**
 * List experiments for the current project. Supports filtering by status and archival state.
 */
export const experimentsList = async (
    projectId: string,
    params?: ExperimentsListParams,
    options?: RequestInit
): Promise<PaginatedExperimentBasicListApi> => {
    return apiMutator<PaginatedExperimentBasicListApi>(getExperimentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/`
}

/**
 * Create a new experiment in draft status with optional metrics.
 */
export const experimentsCreate = async (
    projectId: string,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentApi),
    })
}

export const getExperimentsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

/**
 * Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.
 */
export const experimentsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsUpdate = async (
    projectId: string,
    id: number,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentApi),
    })
}

export const getExperimentsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

/**
 * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time.
 */
export const experimentsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedExperimentApi?: NonReadonly<PatchedExperimentApi>,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExperimentApi),
    })
}

export const getExperimentsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const experimentsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getExperimentsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getExperimentsArchiveCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/archive/`
}

/**
 * Archive an ended experiment.
 *
 * Hides the experiment from the default list view. The experiment can be
 * restored at any time by updating archived=false. When the linked feature
 * flag is still enabled, pass disable_feature_flag=true to also disable and
 * archive it. Returns 400 if the experiment is already archived or has not
 * ended yet.
 */
export const experimentsArchiveCreate = async (
    projectId: string,
    id: number,
    archiveExperimentApi?: ArchiveExperimentApi,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsArchiveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(archiveExperimentApi),
    })
}

export const getExperimentsCopyToProjectCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/copy_to_project/`
}

/**
 * Copy an experiment into another project in the same organization as a new draft.
 */
export const experimentsCopyToProjectCreate = async (
    projectId: string,
    id: number,
    copyExperimentToProjectApi: CopyExperimentToProjectApi,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsCopyToProjectCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(copyExperimentToProjectApi),
    })
}

export const getExperimentsCreateExposureCohortForExperimentCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/create_exposure_cohort_for_experiment/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsCreateExposureCohortForExperimentCreate = async (
    projectId: string,
    id: number,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsCreateExposureCohortForExperimentCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentApi),
    })
}

export const getExperimentsDuplicateCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/duplicate/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsDuplicateCreate = async (
    projectId: string,
    id: number,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsDuplicateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentApi),
    })
}

export const getExperimentsEndCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/end/`
}

/**
 * End a running experiment without shipping a variant.
 *
 * Sets end_date to now and marks the experiment as stopped. The feature
 * flag is NOT modified — users continue to see their assigned variants
 * and exposure events ($feature_flag_called) continue to be recorded.
 * However, only data up to end_date is included in experiment results.
 *
 * Use this when:
 *
 * - You want to freeze the results window without changing which variant
 *   users see.
 * - A variant was already shipped manually via the feature flag UI and
 *   the experiment just needs to be marked complete.
 *
 * The end_date can be adjusted after ending via PATCH if it needs to be
 * backdated (e.g. to match when the flag was actually paused).
 *
 * Other options:
 * - Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
 * - Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).
 *
 * Returns 400 if the experiment is not running.
 */
export const experimentsEndCreate = async (
    projectId: string,
    id: number,
    endExperimentApi?: EndExperimentApi,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsEndCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endExperimentApi),
    })
}

export const getExperimentsLaunchCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/launch/`
}

/**
 * Launch a draft experiment.
 *
 * Validates the experiment is in draft state, activates its linked feature flag,
 * sets start_date to the current server time, and transitions the experiment to running.
 * Returns 400 if the experiment has already been launched or if the feature flag
 * configuration is invalid (e.g. missing "control" variant or fewer than 2 variants).
 */
export const experimentsLaunchCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsLaunchCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getExperimentsMetricsRecalculationCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/metrics_recalculation/`
}

/**
 * Trigger a batch recalculation of all metrics for this experiment.
 *
 * Returns 201 with the new pending recalculation, or 200 with the active one if a recalculation is
 * already pending or in progress for this experiment. The response payload intentionally does not
 * include the `results` array — at POST time the workflow has just been queued and no per-metric
 * results exist yet. Clients should poll `GET metrics_recalculation/{id}/` for results as the workflow
 * progresses.
 */
export const experimentsMetricsRecalculationCreate = async (
    projectId: string,
    id: number,
    recalculateMetricsRequestApi?: RecalculateMetricsRequestApi,
    options?: RequestInit
): Promise<ExperimentMetricsRecalculationApi> => {
    return apiMutator<ExperimentMetricsRecalculationApi>(getExperimentsMetricsRecalculationCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(recalculateMetricsRequestApi),
    })
}

export const getExperimentsMetricsRecalculationRetrieveUrl = (
    projectId: string,
    id: number,
    recalculationId: string
) => {
    return `/api/projects/${projectId}/experiments/${id}/metrics_recalculation/${recalculationId}/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsMetricsRecalculationRetrieve = async (
    projectId: string,
    id: number,
    recalculationId: string,
    options?: RequestInit
): Promise<ExperimentMetricsRecalculationApi> => {
    return apiMutator<ExperimentMetricsRecalculationApi>(
        getExperimentsMetricsRecalculationRetrieveUrl(projectId, id, recalculationId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getExperimentsMetricsRecalculationLatestRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/metrics_recalculation/latest/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsMetricsRecalculationLatestRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentMetricsRecalculationApi> => {
    return apiMutator<ExperimentMetricsRecalculationApi>(
        getExperimentsMetricsRecalculationLatestRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getExperimentsPauseCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/pause/`
}

/**
 * Pause a running experiment.
 *
 * Deactivates the linked feature flag so it is no longer returned by the
 * /decide endpoint. Users fall back to the application default (typically
 * the control experience), and no new exposure events are recorded (i.e.
 * $feature_flag_called is not fired).
 * Returns 400 if the experiment is not running or is already paused.
 */
export const experimentsPauseCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsPauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getExperimentsRecalculateTimeseriesCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/recalculate_timeseries/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsRecalculateTimeseriesCreate = async (
    projectId: string,
    id: number,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsRecalculateTimeseriesCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentApi),
    })
}

export const getExperimentsResetCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/reset/`
}

/**
 * Reset an experiment back to draft state.
 *
 * Clears start/end dates, conclusion, and archived flag. The feature
 * flag is left unchanged — users continue to see their assigned variants.
 *
 * Previously collected events still exist but won't be included in
 * results unless the start date is manually adjusted after re-launch.
 *
 * Returns 400 if the experiment is already in draft state.
 */
export const experimentsResetCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsResetCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getExperimentsResumeCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/resume/`
}

/**
 * Resume a paused experiment.
 *
 * Reactivates the linked feature flag so it is returned by /decide again.
 * Users are re-bucketed deterministically into the same variants they had
 * before the pause, and exposure tracking resumes.
 * Returns 400 if the experiment is not running or is not paused.
 */
export const experimentsResumeCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsResumeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getExperimentsShipVariantCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/ship_variant/`
}

/**
 * Ship a variant and (optionally) end the experiment.
 *
 * Updates the feature flag so the selected variant gets 100% of the variant
 * distribution. By default, existing release conditions on the flag are preserved
 * untouched — the variant is served only to users who already match them. Pass
 * ``release_to_everyone: true`` to also prepend a catch-all release condition
 * that rolls the variant out to 100% of users (overrides any existing release
 * conditions on the flag).
 *
 * Can be called on both running and stopped experiments. If the experiment is
 * still running, it will also be ended (end_date set and status marked as stopped).
 * If the experiment has already ended, only the flag is rewritten - this supports
 * the "end first, ship later" workflow.
 *
 * If an approval policy requires review before changes on the flag take effect,
 * the API returns 409 with a change_request_id. The experiment is NOT ended until
 * the change request is approved and the user retries.
 *
 * Returns 400 if the experiment is in draft state, the variant_key is not found
 * on the flag, or the experiment has no linked feature flag.
 */
export const experimentsShipVariantCreate = async (
    projectId: string,
    id: number,
    shipVariantApi: ShipVariantApi,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsShipVariantCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(shipVariantApi),
    })
}

export const getExperimentsTimeseriesResultsRetrieveUrl = (
    projectId: string,
    id: number,
    params: ExperimentsTimeseriesResultsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/experiments/${id}/timeseries_results/?${stringifiedParams}`
        : `/api/projects/${projectId}/experiments/${id}/timeseries_results/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsTimeseriesResultsRetrieve = async (
    projectId: string,
    id: number,
    params: ExperimentsTimeseriesResultsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsTimeseriesResultsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentsUnarchiveCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/unarchive/`
}

/**
 * Unarchive an archived experiment.
 *
 * Restores the experiment to the default list view. Returns 400 if the
 * experiment is not currently archived.
 */
export const experimentsUnarchiveCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsUnarchiveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getExperimentsCalculateRunningTimeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/calculate_running_time/`
}

/**
 * Estimate the recommended sample size and running time for an experiment.
 *
 * Pure statistical calculation — does not read or write any experiment. Pass the metric type, a
 * minimum detectable effect, and either a baseline value or raw baseline statistics. When
 * `exposure_rate_per_day` is provided, the response also includes the estimated running time in days.
 */
export const experimentsCalculateRunningTimeCreate = async (
    projectId: string,
    runningTimeCalculationInputApi: RunningTimeCalculationInputApi,
    options?: RequestInit
): Promise<RunningTimeCalculationResultApi> => {
    return apiMutator<RunningTimeCalculationResultApi>(getExperimentsCalculateRunningTimeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(runningTimeCalculationInputApi),
    })
}

export const getExperimentsCreateFromPromptCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/create_from_prompt/`
}

/**
 * Create an experiment that compares N versions of an LLM prompt using a metric template.
 *
 * The user picks 2+ versions of an existing LLMPrompt and 1+ metric templates
 * (cost / latency / eval_pass_rate). The endpoint builds the matching variants
 * (control + test-N, each named after its prompt version) and attaches one
 * metric per selected template, each scoped to the prompt's $ai_prompt_name.
 * Resulting experiment is in draft state.
 */
export const experimentsCreateFromPromptCreate = async (
    projectId: string,
    createFromPromptInputApi: CreateFromPromptInputApi,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsCreateFromPromptCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createFromPromptInputApi),
    })
}

export const getExperimentsEligibleFeatureFlagsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/eligible_feature_flags/`
}

/**
 * Returns a paginated list of feature flags eligible for use in experiments.
 *
 * Eligible flags must:
 * - Be multivariate with at least 2 variants
 * - Have "control" as the first variant key
 *
 * Query parameters:
 * - search: Filter by flag key or name (case insensitive)
 * - limit: Number of results per page (default: 20)
 * - offset: Pagination offset (default: 0)
 * - active: Filter by active status ("true" or "false")
 * - created_by_id: Filter by creator user ID
 * - order: Sort order field
 * - evaluation_runtime: Filter by evaluation runtime
 * - has_evaluation_contexts: Filter by presence of evaluation contexts ("true" or "false")
 */
export const experimentsEligibleFeatureFlagsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsEligibleFeatureFlagsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentsPromptTemplatesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/prompt_templates/`
}

/**
 * List the LLM metric templates that can be passed to `create_from_prompt`.
 */
export const experimentsPromptTemplatesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ExperimentsPromptTemplatesRetrieve200Item[]> => {
    return apiMutator<ExperimentsPromptTemplatesRetrieve200Item[]>(
        getExperimentsPromptTemplatesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getExperimentsRequiresFlagImplementationRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/requires_flag_implementation/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsRequiresFlagImplementationRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsRequiresFlagImplementationRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentsStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/stats/`
}

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.
 *
 * This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
 * on serializer methods and converts them into proper HTTP 409 Conflict responses with
 * change request details.
 */
export const experimentsStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getExperimentsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
