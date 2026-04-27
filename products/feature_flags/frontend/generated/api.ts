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
    ActivityLogPaginatedResponseApi,
    BulkUpdateTagsRequestApi,
    BulkUpdateTagsResponseApi,
    CopyFlagsRequestApi,
    CopyFlagsResponseApi,
    DependentFlagApi,
    FeatureFlagApi,
    FeatureFlagCreateRequestSchemaApi,
    FeatureFlagStatusResponseApi,
    FeatureFlagVersionResponseApi,
    FeatureFlagsActivityRetrieveParams,
    FeatureFlagsAllActivityRetrieveParams,
    FeatureFlagsEvaluationReasonsRetrieveParams,
    FeatureFlagsListParams,
    FeatureFlagsLocalEvaluationRetrieveParams,
    FeatureFlagsMyFlagsRetrieveParams,
    LocalEvaluationResponseApi,
    MyFlagsResponseApi,
    PaginatedFeatureFlagListApi,
    PaginatedScheduledChangeListApi,
    PatchedFeatureFlagPartialUpdateRequestSchemaApi,
    PatchedScheduledChangeApi,
    ScheduledChangeApi,
    ScheduledChangesListParams,
    UserBlastRadiusRequestApi,
    UserBlastRadiusResponseApi,
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

export const getOrgFeatureFlagsRetrieveUrl = (organizationId: string, featureFlagKey: string) => {
    return `/api/organizations/${organizationId}/feature_flags/${featureFlagKey}/`
}

export const orgFeatureFlagsRetrieve = async (
    organizationId: string,
    featureFlagKey: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getOrgFeatureFlagsRetrieveUrl(organizationId, featureFlagKey), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureFlagsCopyFlagsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/feature_flags/copy_flags/`
}

export const featureFlagsCopyFlagsCreate = async (
    organizationId: string,
    copyFlagsRequestApi: CopyFlagsRequestApi,
    options?: RequestInit
): Promise<CopyFlagsResponseApi> => {
    return apiMutator<CopyFlagsResponseApi>(getFeatureFlagsCopyFlagsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(copyFlagsRequestApi),
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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
): Promise<PaginatedFeatureFlagListApi> => {
    return apiMutator<PaginatedFeatureFlagListApi>(getFeatureFlagsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/`
}

export const featureFlagsCreate = async (
    projectId: string,
    featureFlagCreateRequestSchemaApi: FeatureFlagCreateRequestSchemaApi,
    options?: RequestInit
): Promise<FeatureFlagApi> => {
    return apiMutator<FeatureFlagApi>(getFeatureFlagsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagCreateRequestSchemaApi),
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

export const featureFlagsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<FeatureFlagApi> => {
    return apiMutator<FeatureFlagApi>(getFeatureFlagsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

export const featureFlagsUpdate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<FeatureFlagApi> => {
    return apiMutator<FeatureFlagApi>(getFeatureFlagsUpdateUrl(projectId, id), {
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
export const getFeatureFlagsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

export const featureFlagsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedFeatureFlagPartialUpdateRequestSchemaApi: PatchedFeatureFlagPartialUpdateRequestSchemaApi,
    options?: RequestInit
): Promise<FeatureFlagApi> => {
    return apiMutator<FeatureFlagApi>(getFeatureFlagsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFeatureFlagPartialUpdateRequestSchemaApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getFeatureFlagsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

export const featureFlagsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getFeatureFlagsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsActivityRetrieveUrl = (
    projectId: string,
    id: number,
    params?: FeatureFlagsActivityRetrieveParams
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

export const featureFlagsActivityRetrieve = async (
    projectId: string,
    id: number,
    params?: FeatureFlagsActivityRetrieveParams,
    options?: RequestInit
): Promise<ActivityLogPaginatedResponseApi> => {
    return apiMutator<ActivityLogPaginatedResponseApi>(getFeatureFlagsActivityRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsCreateStaticCohortForFlagCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/create_static_cohort_for_flag/`
}

export const featureFlagsCreateStaticCohortForFlagCreate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsCreateStaticCohortForFlagCreateUrl(projectId, id), {
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
export const getFeatureFlagsDashboardCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/dashboard/`
}

export const featureFlagsDashboardCreate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsDashboardCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagApi),
    })
}

/**
 * Get other active flags that depend on this flag.
 */
export const getFeatureFlagsDependentFlagsListUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/dependent_flags/`
}

export const featureFlagsDependentFlagsList = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<DependentFlagApi[]> => {
    return apiMutator<DependentFlagApi[]>(getFeatureFlagsDependentFlagsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsEnrichUsageDashboardCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/enrich_usage_dashboard/`
}

export const featureFlagsEnrichUsageDashboardCreate = async (
    projectId: string,
    id: number,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsEnrichUsageDashboardCreateUrl(projectId, id), {
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
export const getFeatureFlagsRemoteConfigRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/remote_config/`
}

export const featureFlagsRemoteConfigRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsRemoteConfigRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsStatusRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/status/`
}

export const featureFlagsStatusRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<FeatureFlagStatusResponseApi> => {
    return apiMutator<FeatureFlagStatusResponseApi>(getFeatureFlagsStatusRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsVersionsRetrieveUrl = (projectId: string, id: number, versionNumber: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/versions/${versionNumber}/`
}

export const featureFlagsVersionsRetrieve = async (
    projectId: string,
    id: number,
    versionNumber: number,
    options?: RequestInit
): Promise<FeatureFlagVersionResponseApi> => {
    return apiMutator<FeatureFlagVersionResponseApi>(getFeatureFlagsVersionsRetrieveUrl(projectId, id, versionNumber), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsAllActivityRetrieveUrl = (
    projectId: string,
    params?: FeatureFlagsAllActivityRetrieveParams
) => {
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

export const featureFlagsAllActivityRetrieve = async (
    projectId: string,
    params?: FeatureFlagsAllActivityRetrieveParams,
    options?: RequestInit
): Promise<ActivityLogPaginatedResponseApi> => {
    return apiMutator<ActivityLogPaginatedResponseApi>(getFeatureFlagsAllActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Bulk delete feature flags by filter criteria or explicit IDs.

Accepts either:
- {"filters": {...}} - Same filter params as list endpoint (search, active, type, etc.)
- {"ids": [...]} - Explicit list of flag IDs (no limit)

Returns same format as bulk_delete for UI compatibility.

Uses bulk operations for efficiency: database updates are batched and cache
invalidation happens once at the end rather than per-flag.
 */
export const getFeatureFlagsBulkDeleteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/bulk_delete/`
}

export const featureFlagsBulkDeleteCreate = async (
    projectId: string,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsBulkDeleteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagApi),
    })
}

/**
 * Get feature flag keys by IDs.
Accepts a list of feature flag IDs and returns a mapping of ID to key.
 */
export const getFeatureFlagsBulkKeysCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/bulk_keys/`
}

export const featureFlagsBulkKeysCreate = async (
    projectId: string,
    featureFlagApi: NonReadonly<FeatureFlagApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsBulkKeysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagApi),
    })
}

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const getFeatureFlagsBulkUpdateTagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/bulk_update_tags/`
}

export const featureFlagsBulkUpdateTagsCreate = async (
    projectId: string,
    bulkUpdateTagsRequestApi: BulkUpdateTagsRequestApi,
    options?: RequestInit
): Promise<BulkUpdateTagsResponseApi> => {
    return apiMutator<BulkUpdateTagsResponseApi>(getFeatureFlagsBulkUpdateTagsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkUpdateTagsRequestApi),
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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
): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsEvaluationReasonsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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
): Promise<LocalEvaluationResponseApi> => {
    return apiMutator<LocalEvaluationResponseApi>(getFeatureFlagsLocalEvaluationRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get IDs of all feature flags matching the current filters.
Uses the same filtering logic as the list endpoint.
Returns only IDs that the user has permission to edit.
 */
export const getFeatureFlagsMatchingIdsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/matching_ids/`
}

export const featureFlagsMatchingIdsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsMatchingIdsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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
): Promise<MyFlagsResponseApi[]> => {
    return apiMutator<MyFlagsResponseApi[]>(getFeatureFlagsMyFlagsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const getFeatureFlagsUserBlastRadiusCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/user_blast_radius/`
}

export const featureFlagsUserBlastRadiusCreate = async (
    projectId: string,
    userBlastRadiusRequestApi: UserBlastRadiusRequestApi,
    options?: RequestInit
): Promise<UserBlastRadiusResponseApi> => {
    return apiMutator<UserBlastRadiusResponseApi>(getFeatureFlagsUserBlastRadiusCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userBlastRadiusRequestApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesListUrl = (projectId: string, params?: ScheduledChangesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/scheduled_changes/?${stringifiedParams}`
        : `/api/projects/${projectId}/scheduled_changes/`
}

export const scheduledChangesList = async (
    projectId: string,
    params?: ScheduledChangesListParams,
    options?: RequestInit
): Promise<PaginatedScheduledChangeListApi> => {
    return apiMutator<PaginatedScheduledChangeListApi>(getScheduledChangesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/scheduled_changes/`
}

export const scheduledChangesCreate = async (
    projectId: string,
    scheduledChangeApi: NonReadonly<ScheduledChangeApi>,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesUpdate = async (
    projectId: string,
    id: number,
    scheduledChangeApi: NonReadonly<ScheduledChangeApi>,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesPartialUpdate = async (
    projectId: string,
    id: number,
    patchedScheduledChangeApi: NonReadonly<PatchedScheduledChangeApi>,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedScheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getScheduledChangesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
