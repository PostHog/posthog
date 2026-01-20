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
    ActivityLogPaginatedResponseApi,
    FeatureFlagApi,
    FeatureFlagsActivityRetrieve2Params,
    FeatureFlagsActivityRetrieveParams,
    FeatureFlagsEvaluationReasonsRetrieveParams,
    FeatureFlagsListParams,
    FeatureFlagsLocalEvaluationRetrieve402,
    FeatureFlagsLocalEvaluationRetrieve500,
    FeatureFlagsLocalEvaluationRetrieveParams,
    FeatureFlagsMyFlagsRetrieveParams,
    LocalEvaluationResponseApi,
    MyFlagsResponseApi,
    PaginatedFeatureFlagListApi,
    PatchedFeatureFlagApi,
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
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsListResponse200 = {
    data: PaginatedFeatureFlagListApi
    status: 200
}

export type featureFlagsListResponseSuccess = featureFlagsListResponse200 & {
    headers: Headers
}
export type featureFlagsListResponse = featureFlagsListResponseSuccess

export const getFeatureFlagsListUrl = (projectId: string, params?: FeatureFlagsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/`
}

export const featureFlagsList = async (
    projectId: string,
    params?: FeatureFlagsListParams,
    options?: RequestInit
): Promise<featureFlagsListResponse> => {
    return apiMutator<featureFlagsListResponse>(getFeatureFlagsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsCreateResponse201 = {
    data: FeatureFlagApi
    status: 201
}

export type featureFlagsCreateResponseSuccess = featureFlagsCreateResponse201 & {
    headers: Headers
}
export type featureFlagsCreateResponse = featureFlagsCreateResponseSuccess

export const getFeatureFlagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/`
}

export const featureFlagsCreate = async (
    projectId: string,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsCreateResponse> => {
    return apiMutator<featureFlagsCreateResponse>(getFeatureFlagsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagApi),
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsRetrieve2Response200 = {
    data: FeatureFlagApi
    status: 200
}

export type featureFlagsRetrieve2ResponseSuccess = featureFlagsRetrieve2Response200 & {
    headers: Headers
}
export type featureFlagsRetrieve2Response = featureFlagsRetrieve2ResponseSuccess

export const getFeatureFlagsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

export const featureFlagsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<featureFlagsRetrieve2Response> => {
    return apiMutator<featureFlagsRetrieve2Response>(getFeatureFlagsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsUpdateResponse200 = {
    data: FeatureFlagApi
    status: 200
}

export type featureFlagsUpdateResponseSuccess = featureFlagsUpdateResponse200 & {
    headers: Headers
}
export type featureFlagsUpdateResponse = featureFlagsUpdateResponseSuccess

export const getFeatureFlagsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

export const featureFlagsUpdate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsUpdateResponse> => {
    return apiMutator<featureFlagsUpdateResponse>(getFeatureFlagsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagApi),
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsPartialUpdateResponse200 = {
    data: FeatureFlagApi
    status: 200
}

export type featureFlagsPartialUpdateResponseSuccess = featureFlagsPartialUpdateResponse200 & {
    headers: Headers
}
export type featureFlagsPartialUpdateResponse = featureFlagsPartialUpdateResponseSuccess

export const getFeatureFlagsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

export const featureFlagsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedFeatureFlagApi: NonReadonly<PatchedFeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsPartialUpdateResponse> => {
    return apiMutator<featureFlagsPartialUpdateResponse>(getFeatureFlagsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFeatureFlagApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type featureFlagsDestroyResponse405 = {
    data: void
    status: 405
}
export type featureFlagsDestroyResponseError = featureFlagsDestroyResponse405 & {
    headers: Headers
}

export type featureFlagsDestroyResponse = featureFlagsDestroyResponseError

export const getFeatureFlagsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

export const featureFlagsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<featureFlagsDestroyResponse> => {
    return apiMutator<featureFlagsDestroyResponse>(getFeatureFlagsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsActivityRetrieve2Response200 = {
    data: ActivityLogPaginatedResponseApi
    status: 200
}

export type featureFlagsActivityRetrieve2Response404 = {
    data: void
    status: 404
}

export type featureFlagsActivityRetrieve2ResponseSuccess = featureFlagsActivityRetrieve2Response200 & {
    headers: Headers
}
export type featureFlagsActivityRetrieve2ResponseError = featureFlagsActivityRetrieve2Response404 & {
    headers: Headers
}

export type featureFlagsActivityRetrieve2Response =
    | featureFlagsActivityRetrieve2ResponseSuccess
    | featureFlagsActivityRetrieve2ResponseError

export const getFeatureFlagsActivityRetrieve2Url = (
    projectId: string,
    id: number,
    params?: FeatureFlagsActivityRetrieve2Params
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/${id}/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/${id}/activity/`
}

export const featureFlagsActivityRetrieve2 = async (
    projectId: string,
    id: number,
    params?: FeatureFlagsActivityRetrieve2Params,
    options?: RequestInit
): Promise<featureFlagsActivityRetrieve2Response> => {
    return apiMutator<featureFlagsActivityRetrieve2Response>(
        getFeatureFlagsActivityRetrieve2Url(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsCreateStaticCohortForFlagCreateResponse200 = {
    data: void
    status: 200
}

export type featureFlagsCreateStaticCohortForFlagCreateResponseSuccess =
    featureFlagsCreateStaticCohortForFlagCreateResponse200 & {
        headers: Headers
    }
export type featureFlagsCreateStaticCohortForFlagCreateResponse =
    featureFlagsCreateStaticCohortForFlagCreateResponseSuccess

export const getFeatureFlagsCreateStaticCohortForFlagCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/create_static_cohort_for_flag/`
}

export const featureFlagsCreateStaticCohortForFlagCreate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsCreateStaticCohortForFlagCreateResponse> => {
    return apiMutator<featureFlagsCreateStaticCohortForFlagCreateResponse>(
        getFeatureFlagsCreateStaticCohortForFlagCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(featureFlagApi),
        }
    )
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsDashboardCreateResponse200 = {
    data: void
    status: 200
}

export type featureFlagsDashboardCreateResponseSuccess = featureFlagsDashboardCreateResponse200 & {
    headers: Headers
}
export type featureFlagsDashboardCreateResponse = featureFlagsDashboardCreateResponseSuccess

export const getFeatureFlagsDashboardCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/dashboard/`
}

export const featureFlagsDashboardCreate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsDashboardCreateResponse> => {
    return apiMutator<featureFlagsDashboardCreateResponse>(getFeatureFlagsDashboardCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagApi),
    })
}

/**
 * Get other active flags that depend on this flag.
 */
export type featureFlagsDependentFlagsRetrieveResponse200 = {
    data: void
    status: 200
}

export type featureFlagsDependentFlagsRetrieveResponseSuccess = featureFlagsDependentFlagsRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsDependentFlagsRetrieveResponse = featureFlagsDependentFlagsRetrieveResponseSuccess

export const getFeatureFlagsDependentFlagsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/dependent_flags/`
}

export const featureFlagsDependentFlagsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<featureFlagsDependentFlagsRetrieveResponse> => {
    return apiMutator<featureFlagsDependentFlagsRetrieveResponse>(
        getFeatureFlagsDependentFlagsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsEnrichUsageDashboardCreateResponse200 = {
    data: void
    status: 200
}

export type featureFlagsEnrichUsageDashboardCreateResponseSuccess =
    featureFlagsEnrichUsageDashboardCreateResponse200 & {
        headers: Headers
    }
export type featureFlagsEnrichUsageDashboardCreateResponse = featureFlagsEnrichUsageDashboardCreateResponseSuccess

export const getFeatureFlagsEnrichUsageDashboardCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/enrich_usage_dashboard/`
}

export const featureFlagsEnrichUsageDashboardCreate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsEnrichUsageDashboardCreateResponse> => {
    return apiMutator<featureFlagsEnrichUsageDashboardCreateResponse>(
        getFeatureFlagsEnrichUsageDashboardCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(featureFlagApi),
        }
    )
}

/**
 * Deprecated: Use GET /dependent_flags instead.
Safe to delete after usage falls to zero, expected by Jan 22, 2026.
 */
export type featureFlagsHasActiveDependentsCreateResponse200 = {
    data: void
    status: 200
}

export type featureFlagsHasActiveDependentsCreateResponseSuccess = featureFlagsHasActiveDependentsCreateResponse200 & {
    headers: Headers
}
export type featureFlagsHasActiveDependentsCreateResponse = featureFlagsHasActiveDependentsCreateResponseSuccess

export const getFeatureFlagsHasActiveDependentsCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/has_active_dependents/`
}

export const featureFlagsHasActiveDependentsCreate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsHasActiveDependentsCreateResponse> => {
    return apiMutator<featureFlagsHasActiveDependentsCreateResponse>(
        getFeatureFlagsHasActiveDependentsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(featureFlagApi),
        }
    )
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsRemoteConfigRetrieveResponse200 = {
    data: void
    status: 200
}

export type featureFlagsRemoteConfigRetrieveResponseSuccess = featureFlagsRemoteConfigRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsRemoteConfigRetrieveResponse = featureFlagsRemoteConfigRetrieveResponseSuccess

export const getFeatureFlagsRemoteConfigRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/remote_config/`
}

export const featureFlagsRemoteConfigRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<featureFlagsRemoteConfigRetrieveResponse> => {
    return apiMutator<featureFlagsRemoteConfigRetrieveResponse>(getFeatureFlagsRemoteConfigRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsStatusRetrieveResponse200 = {
    data: void
    status: 200
}

export type featureFlagsStatusRetrieveResponseSuccess = featureFlagsStatusRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsStatusRetrieveResponse = featureFlagsStatusRetrieveResponseSuccess

export const getFeatureFlagsStatusRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/status/`
}

export const featureFlagsStatusRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<featureFlagsStatusRetrieveResponse> => {
    return apiMutator<featureFlagsStatusRetrieveResponse>(getFeatureFlagsStatusRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsActivityRetrieveResponse200 = {
    data: ActivityLogPaginatedResponseApi
    status: 200
}

export type featureFlagsActivityRetrieveResponseSuccess = featureFlagsActivityRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsActivityRetrieveResponse = featureFlagsActivityRetrieveResponseSuccess

export const getFeatureFlagsActivityRetrieveUrl = (projectId: string, params?: FeatureFlagsActivityRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/activity/`
}

export const featureFlagsActivityRetrieve = async (
    projectId: string,
    params?: FeatureFlagsActivityRetrieveParams,
    options?: RequestInit
): Promise<featureFlagsActivityRetrieveResponse> => {
    return apiMutator<featureFlagsActivityRetrieveResponse>(getFeatureFlagsActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get feature flag keys by IDs.
Accepts a list of feature flag IDs and returns a mapping of ID to key.
 */
export type featureFlagsBulkKeysCreateResponse200 = {
    data: void
    status: 200
}

export type featureFlagsBulkKeysCreateResponseSuccess = featureFlagsBulkKeysCreateResponse200 & {
    headers: Headers
}
export type featureFlagsBulkKeysCreateResponse = featureFlagsBulkKeysCreateResponseSuccess

export const getFeatureFlagsBulkKeysCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/bulk_keys/`
}

export const featureFlagsBulkKeysCreate = async (
    projectId: string,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsBulkKeysCreateResponse> => {
    return apiMutator<featureFlagsBulkKeysCreateResponse>(getFeatureFlagsBulkKeysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagApi),
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsEvaluationReasonsRetrieveResponse200 = {
    data: void
    status: 200
}

export type featureFlagsEvaluationReasonsRetrieveResponseSuccess = featureFlagsEvaluationReasonsRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsEvaluationReasonsRetrieveResponse = featureFlagsEvaluationReasonsRetrieveResponseSuccess

export const getFeatureFlagsEvaluationReasonsRetrieveUrl = (
    projectId: string,
    params: FeatureFlagsEvaluationReasonsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/evaluation_reasons/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/evaluation_reasons/`
}

export const featureFlagsEvaluationReasonsRetrieve = async (
    projectId: string,
    params: FeatureFlagsEvaluationReasonsRetrieveParams,
    options?: RequestInit
): Promise<featureFlagsEvaluationReasonsRetrieveResponse> => {
    return apiMutator<featureFlagsEvaluationReasonsRetrieveResponse>(
        getFeatureFlagsEvaluationReasonsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsLocalEvaluationRetrieveResponse200 = {
    data: LocalEvaluationResponseApi
    status: 200
}

export type featureFlagsLocalEvaluationRetrieveResponse402 = {
    data: FeatureFlagsLocalEvaluationRetrieve402
    status: 402
}

export type featureFlagsLocalEvaluationRetrieveResponse500 = {
    data: FeatureFlagsLocalEvaluationRetrieve500
    status: 500
}

export type featureFlagsLocalEvaluationRetrieveResponseSuccess = featureFlagsLocalEvaluationRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsLocalEvaluationRetrieveResponseError = (
    | featureFlagsLocalEvaluationRetrieveResponse402
    | featureFlagsLocalEvaluationRetrieveResponse500
) & {
    headers: Headers
}

export type featureFlagsLocalEvaluationRetrieveResponse =
    | featureFlagsLocalEvaluationRetrieveResponseSuccess
    | featureFlagsLocalEvaluationRetrieveResponseError

export const getFeatureFlagsLocalEvaluationRetrieveUrl = (
    projectId: string,
    params?: FeatureFlagsLocalEvaluationRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/local_evaluation/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/local_evaluation/`
}

export const featureFlagsLocalEvaluationRetrieve = async (
    projectId: string,
    params?: FeatureFlagsLocalEvaluationRetrieveParams,
    options?: RequestInit
): Promise<featureFlagsLocalEvaluationRetrieveResponse> => {
    return apiMutator<featureFlagsLocalEvaluationRetrieveResponse>(
        getFeatureFlagsLocalEvaluationRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsMyFlagsRetrieveResponse200 = {
    data: MyFlagsResponseApi[]
    status: 200
}

export type featureFlagsMyFlagsRetrieveResponseSuccess = featureFlagsMyFlagsRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsMyFlagsRetrieveResponse = featureFlagsMyFlagsRetrieveResponseSuccess

export const getFeatureFlagsMyFlagsRetrieveUrl = (projectId: string, params?: FeatureFlagsMyFlagsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/my_flags/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/my_flags/`
}

export const featureFlagsMyFlagsRetrieve = async (
    projectId: string,
    params?: FeatureFlagsMyFlagsRetrieveParams,
    options?: RequestInit
): Promise<featureFlagsMyFlagsRetrieveResponse> => {
    return apiMutator<featureFlagsMyFlagsRetrieveResponse>(getFeatureFlagsMyFlagsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsUserBlastRadiusCreateResponse200 = {
    data: void
    status: 200
}

export type featureFlagsUserBlastRadiusCreateResponseSuccess = featureFlagsUserBlastRadiusCreateResponse200 & {
    headers: Headers
}
export type featureFlagsUserBlastRadiusCreateResponse = featureFlagsUserBlastRadiusCreateResponseSuccess

export const getFeatureFlagsUserBlastRadiusCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/user_blast_radius/`
}

export const featureFlagsUserBlastRadiusCreate = async (
    projectId: string,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<featureFlagsUserBlastRadiusCreateResponse> => {
    return apiMutator<featureFlagsUserBlastRadiusCreateResponse>(getFeatureFlagsUserBlastRadiusCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagApi),
    })
}
