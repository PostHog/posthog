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

export type experimentHoldoutsListResponse200 = {
    data: PaginatedExperimentHoldoutListApi
    status: 200
}

export type experimentHoldoutsListResponseSuccess = experimentHoldoutsListResponse200 & {
    headers: Headers
}
export type experimentHoldoutsListResponse = experimentHoldoutsListResponseSuccess

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
): Promise<experimentHoldoutsListResponse> => {
    return apiMutator<experimentHoldoutsListResponse>(getExperimentHoldoutsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type experimentHoldoutsCreateResponse201 = {
    data: ExperimentHoldoutApi
    status: 201
}

export type experimentHoldoutsCreateResponseSuccess = experimentHoldoutsCreateResponse201 & {
    headers: Headers
}
export type experimentHoldoutsCreateResponse = experimentHoldoutsCreateResponseSuccess

export const getExperimentHoldoutsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiment_holdouts/`
}

export const experimentHoldoutsCreate = async (
    projectId: string,
    experimentHoldoutApi: NonReadonly<ExperimentHoldoutApi>,
    options?: RequestInit
): Promise<experimentHoldoutsCreateResponse> => {
    return apiMutator<experimentHoldoutsCreateResponse>(getExperimentHoldoutsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentHoldoutApi),
    })
}

export type experimentHoldoutsRetrieveResponse200 = {
    data: ExperimentHoldoutApi
    status: 200
}

export type experimentHoldoutsRetrieveResponseSuccess = experimentHoldoutsRetrieveResponse200 & {
    headers: Headers
}
export type experimentHoldoutsRetrieveResponse = experimentHoldoutsRetrieveResponseSuccess

export const getExperimentHoldoutsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_holdouts/${id}/`
}

export const experimentHoldoutsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<experimentHoldoutsRetrieveResponse> => {
    return apiMutator<experimentHoldoutsRetrieveResponse>(getExperimentHoldoutsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type experimentHoldoutsUpdateResponse200 = {
    data: ExperimentHoldoutApi
    status: 200
}

export type experimentHoldoutsUpdateResponseSuccess = experimentHoldoutsUpdateResponse200 & {
    headers: Headers
}
export type experimentHoldoutsUpdateResponse = experimentHoldoutsUpdateResponseSuccess

export const getExperimentHoldoutsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_holdouts/${id}/`
}

export const experimentHoldoutsUpdate = async (
    projectId: string,
    id: number,
    experimentHoldoutApi: NonReadonly<ExperimentHoldoutApi>,
    options?: RequestInit
): Promise<experimentHoldoutsUpdateResponse> => {
    return apiMutator<experimentHoldoutsUpdateResponse>(getExperimentHoldoutsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentHoldoutApi),
    })
}

export type experimentHoldoutsPartialUpdateResponse200 = {
    data: ExperimentHoldoutApi
    status: 200
}

export type experimentHoldoutsPartialUpdateResponseSuccess = experimentHoldoutsPartialUpdateResponse200 & {
    headers: Headers
}
export type experimentHoldoutsPartialUpdateResponse = experimentHoldoutsPartialUpdateResponseSuccess

export const getExperimentHoldoutsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_holdouts/${id}/`
}

export const experimentHoldoutsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedExperimentHoldoutApi: NonReadonly<PatchedExperimentHoldoutApi>,
    options?: RequestInit
): Promise<experimentHoldoutsPartialUpdateResponse> => {
    return apiMutator<experimentHoldoutsPartialUpdateResponse>(getExperimentHoldoutsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExperimentHoldoutApi),
    })
}

export type experimentHoldoutsDestroyResponse204 = {
    data: void
    status: 204
}

export type experimentHoldoutsDestroyResponseSuccess = experimentHoldoutsDestroyResponse204 & {
    headers: Headers
}
export type experimentHoldoutsDestroyResponse = experimentHoldoutsDestroyResponseSuccess

export const getExperimentHoldoutsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiment_holdouts/${id}/`
}

export const experimentHoldoutsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<experimentHoldoutsDestroyResponse> => {
    return apiMutator<experimentHoldoutsDestroyResponse>(getExperimentHoldoutsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type experimentsListResponse200 = {
    data: PaginatedExperimentListApi
    status: 200
}

export type experimentsListResponseSuccess = experimentsListResponse200 & {
    headers: Headers
}
export type experimentsListResponse = experimentsListResponseSuccess

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
): Promise<experimentsListResponse> => {
    return apiMutator<experimentsListResponse>(getExperimentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type experimentsCreateResponse201 = {
    data: ExperimentApi
    status: 201
}

export type experimentsCreateResponseSuccess = experimentsCreateResponse201 & {
    headers: Headers
}
export type experimentsCreateResponse = experimentsCreateResponseSuccess

export const getExperimentsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/`
}

export const experimentsCreate = async (
    projectId: string,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<experimentsCreateResponse> => {
    return apiMutator<experimentsCreateResponse>(getExperimentsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentApi),
    })
}

export type experimentsRetrieveResponse200 = {
    data: ExperimentApi
    status: 200
}

export type experimentsRetrieveResponseSuccess = experimentsRetrieveResponse200 & {
    headers: Headers
}
export type experimentsRetrieveResponse = experimentsRetrieveResponseSuccess

export const getExperimentsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

export const experimentsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<experimentsRetrieveResponse> => {
    return apiMutator<experimentsRetrieveResponse>(getExperimentsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type experimentsUpdateResponse200 = {
    data: ExperimentApi
    status: 200
}

export type experimentsUpdateResponseSuccess = experimentsUpdateResponse200 & {
    headers: Headers
}
export type experimentsUpdateResponse = experimentsUpdateResponseSuccess

export const getExperimentsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

export const experimentsUpdate = async (
    projectId: string,
    id: number,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<experimentsUpdateResponse> => {
    return apiMutator<experimentsUpdateResponse>(getExperimentsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(experimentApi),
    })
}

export type experimentsPartialUpdateResponse200 = {
    data: ExperimentApi
    status: 200
}

export type experimentsPartialUpdateResponseSuccess = experimentsPartialUpdateResponse200 & {
    headers: Headers
}
export type experimentsPartialUpdateResponse = experimentsPartialUpdateResponseSuccess

export const getExperimentsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

export const experimentsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedExperimentApi: NonReadonly<PatchedExperimentApi>,
    options?: RequestInit
): Promise<experimentsPartialUpdateResponse> => {
    return apiMutator<experimentsPartialUpdateResponse>(getExperimentsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExperimentApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type experimentsDestroyResponse405 = {
    data: void
    status: 405
}
export type experimentsDestroyResponseError = experimentsDestroyResponse405 & {
    headers: Headers
}

export type experimentsDestroyResponse = experimentsDestroyResponseError

export const getExperimentsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/`
}

export const experimentsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<experimentsDestroyResponse> => {
    return apiMutator<experimentsDestroyResponse>(getExperimentsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type experimentsCreateExposureCohortForExperimentCreateResponse200 = {
    data: void
    status: 200
}

export type experimentsCreateExposureCohortForExperimentCreateResponseSuccess =
    experimentsCreateExposureCohortForExperimentCreateResponse200 & {
        headers: Headers
    }
export type experimentsCreateExposureCohortForExperimentCreateResponse =
    experimentsCreateExposureCohortForExperimentCreateResponseSuccess

export const getExperimentsCreateExposureCohortForExperimentCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/create_exposure_cohort_for_experiment/`
}

export const experimentsCreateExposureCohortForExperimentCreate = async (
    projectId: string,
    id: number,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<experimentsCreateExposureCohortForExperimentCreateResponse> => {
    return apiMutator<experimentsCreateExposureCohortForExperimentCreateResponse>(
        getExperimentsCreateExposureCohortForExperimentCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(experimentApi),
        }
    )
}

export type experimentsDuplicateCreateResponse200 = {
    data: void
    status: 200
}

export type experimentsDuplicateCreateResponseSuccess = experimentsDuplicateCreateResponse200 & {
    headers: Headers
}
export type experimentsDuplicateCreateResponse = experimentsDuplicateCreateResponseSuccess

export const getExperimentsDuplicateCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/duplicate/`
}

export const experimentsDuplicateCreate = async (
    projectId: string,
    id: number,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<experimentsDuplicateCreateResponse> => {
    return apiMutator<experimentsDuplicateCreateResponse>(getExperimentsDuplicateCreateUrl(projectId, id), {
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
export type experimentsRecalculateTimeseriesCreateResponse200 = {
    data: void
    status: 200
}

export type experimentsRecalculateTimeseriesCreateResponseSuccess =
    experimentsRecalculateTimeseriesCreateResponse200 & {
        headers: Headers
    }
export type experimentsRecalculateTimeseriesCreateResponse = experimentsRecalculateTimeseriesCreateResponseSuccess

export const getExperimentsRecalculateTimeseriesCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/recalculate_timeseries/`
}

export const experimentsRecalculateTimeseriesCreate = async (
    projectId: string,
    id: number,
    experimentApi: NonReadonly<ExperimentApi>,
    options?: RequestInit
): Promise<experimentsRecalculateTimeseriesCreateResponse> => {
    return apiMutator<experimentsRecalculateTimeseriesCreateResponse>(
        getExperimentsRecalculateTimeseriesCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(experimentApi),
        }
    )
}

/**
 * Retrieve timeseries results for a specific experiment-metric combination.
Aggregates daily results into a timeseries format for frontend compatibility.

Query parameters:
- metric_uuid (required): The UUID of the metric to retrieve results for
- fingerprint (required): The fingerprint of the metric configuration
 */
export type experimentsTimeseriesResultsRetrieveResponse200 = {
    data: void
    status: 200
}

export type experimentsTimeseriesResultsRetrieveResponseSuccess = experimentsTimeseriesResultsRetrieveResponse200 & {
    headers: Headers
}
export type experimentsTimeseriesResultsRetrieveResponse = experimentsTimeseriesResultsRetrieveResponseSuccess

export const getExperimentsTimeseriesResultsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/experiments/${id}/timeseries_results/`
}

export const experimentsTimeseriesResultsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<experimentsTimeseriesResultsRetrieveResponse> => {
    return apiMutator<experimentsTimeseriesResultsRetrieveResponse>(
        getExperimentsTimeseriesResultsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
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
export type experimentsEligibleFeatureFlagsRetrieveResponse200 = {
    data: void
    status: 200
}

export type experimentsEligibleFeatureFlagsRetrieveResponseSuccess =
    experimentsEligibleFeatureFlagsRetrieveResponse200 & {
        headers: Headers
    }
export type experimentsEligibleFeatureFlagsRetrieveResponse = experimentsEligibleFeatureFlagsRetrieveResponseSuccess

export const getExperimentsEligibleFeatureFlagsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/eligible_feature_flags/`
}

export const experimentsEligibleFeatureFlagsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<experimentsEligibleFeatureFlagsRetrieveResponse> => {
    return apiMutator<experimentsEligibleFeatureFlagsRetrieveResponse>(
        getExperimentsEligibleFeatureFlagsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type experimentsRequiresFlagImplementationRetrieveResponse200 = {
    data: void
    status: 200
}

export type experimentsRequiresFlagImplementationRetrieveResponseSuccess =
    experimentsRequiresFlagImplementationRetrieveResponse200 & {
        headers: Headers
    }
export type experimentsRequiresFlagImplementationRetrieveResponse =
    experimentsRequiresFlagImplementationRetrieveResponseSuccess

export const getExperimentsRequiresFlagImplementationRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/requires_flag_implementation/`
}

export const experimentsRequiresFlagImplementationRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<experimentsRequiresFlagImplementationRetrieveResponse> => {
    return apiMutator<experimentsRequiresFlagImplementationRetrieveResponse>(
        getExperimentsRequiresFlagImplementationRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get experimentation velocity statistics.
 */
export type experimentsStatsRetrieveResponse200 = {
    data: void
    status: 200
}

export type experimentsStatsRetrieveResponseSuccess = experimentsStatsRetrieveResponse200 & {
    headers: Headers
}
export type experimentsStatsRetrieveResponse = experimentsStatsRetrieveResponseSuccess

export const getExperimentsStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/experiments/stats/`
}

export const experimentsStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<experimentsStatsRetrieveResponse> => {
    return apiMutator<experimentsStatsRetrieveResponse>(getExperimentsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
