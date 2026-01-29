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
    ExperimentApi,
    ExperimentHoldoutApi,
    ExperimentHoldoutsListParams,
    ExperimentsListParams,
    PaginatedExperimentHoldoutListApi,
    PaginatedExperimentListApi,
    PatchedExperimentApi,
    PatchedExperimentHoldoutApi,
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
    patchedExperimentHoldoutApi: NonReadonly<PatchedExperimentHoldoutApi>,
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

export const getExperimentsListUrl = (projectId: string, params?: ExperimentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/experiments/?${stringifiedParams}`
        : `/api/projects/${projectId}/experiments/`
}

export const experimentsList = async (
    projectId: string,
    params?: ExperimentsListParams,
    options?: RequestInit
): Promise<PaginatedExperimentListApi> => {
    return apiMutator<PaginatedExperimentListApi>(getExperimentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/`
}

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

export const experimentsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedExperimentApi: NonReadonly<PatchedExperimentApi>,
    options?: RequestInit
): Promise<ExperimentApi> => {
    return apiMutator<ExperimentApi>(getExperimentsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExperimentApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getExperimentsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

export const experimentsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getExperimentsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getExperimentsCreateExposureCohortForExperimentCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/create_exposure_cohort_for_experiment/`
}

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

/**
 * Create a recalculation request for experiment timeseries data.

Request body:
- metric (required): The full metric object to recalculate
- fingerprint (required): The fingerprint of the metric configuration
 */
export const getExperimentsRecalculateTimeseriesCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/recalculate_timeseries/`
}

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

/**
 * Retrieve timeseries results for a specific experiment-metric combination.
Aggregates daily results into a timeseries format for frontend compatibility.

Query parameters:
- metric_uuid (required): The UUID of the metric to retrieve results for
- fingerprint (required): The fingerprint of the metric configuration
 */
export const getExperimentsTimeseriesResultsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/timeseries_results/`
}

export const experimentsTimeseriesResultsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsTimeseriesResultsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns a paginated list of feature flags eligible for use in experiments.

Eligible flags must:
- Be multivariate with at least 2 variants
- Have "control" as the first variant key

Query parameters:
- search: Filter by flag key or name (case insensitive)
- limit: Number of results per page (default: 20)
- offset: Pagination offset (default: 0)
- active: Filter by active status ("true" or "false")
- created_by_id: Filter by creator user ID
- order: Sort order field
- evaluation_runtime: Filter by evaluation runtime
- has_evaluation_tags: Filter by presence of evaluation tags ("true" or "false")
 */
export const getExperimentsEligibleFeatureFlagsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/eligible_feature_flags/`
}

export const experimentsEligibleFeatureFlagsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsEligibleFeatureFlagsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getExperimentsRequiresFlagImplementationRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/requires_flag_implementation/`
}

export const experimentsRequiresFlagImplementationRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExperimentsRequiresFlagImplementationRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get experimentation velocity statistics.
 */
export const getExperimentsStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/stats/`
}

export const experimentsStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getExperimentsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
