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
    BulkDeleteRequestApi,
    BulkDeleteResponseApi,
    BulkKeysRequestApi,
    BulkKeysResponseApi,
    BulkUpdateTagsRequestApi,
    BulkUpdateTagsResponseApi,
    CopyFlagsRequestApi,
    CopyFlagsResponseApi,
    DependentFlagApi,
    EnvironmentsEvaluationContextSuggestionsDestroyParams,
    EvaluationContextSuggestionRequestApi,
    EvaluationContextSuggestionResponseApi,
    FeatureFlagApi,
    FeatureFlagCreateRequestSchemaApi,
    FeatureFlagStatusResponseApi,
    FeatureFlagTestEvaluationRequestApi,
    FeatureFlagTestEvaluationResponseApi,
    FeatureFlagVersionResponseApi,
    FeatureFlagsActivityRetrieveParams,
    FeatureFlagsAllActivityRetrieveParams,
    FeatureFlagsEvaluationReasonsRetrieveParams,
    FeatureFlagsListParams,
    FeatureFlagsMyFlagsRetrieveParams,
    FeatureFlagsStaffCacheEntryRetrieveParams,
    FeatureFlagsStaffCacheListParams,
    FeatureFlagsStaffTeamsListParams,
    FlagValueResponseApi,
    FlagValueValuesRetrieveParams,
    MyFlagsResponseApi,
    OrgFeatureFlagsKeysParams,
    OrganizationFeatureFlagKeysResponseApi,
    OrganizationsProjectsEvaluationContextSuggestionsDestroyParams,
    PaginatedFeatureFlagListApi,
    PaginatedScheduledChangeListApi,
    PatchedFeatureFlagPartialUpdateRequestSchemaApi,
    PatchedScheduledChangeApi,
    ScheduledChangeApi,
    ScheduledChangesListParams,
    StaffCacheEntryResponseApi,
    StaffCacheMutationApi,
    StaffCacheMutationResponseApi,
    StaffCacheStatusResponseApi,
    StaffTeamSearchResponseApi,
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

export const getFeatureFlagsStaffCacheListUrl = (params: FeatureFlagsStaffCacheListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/feature_flags_staff_cache/?${stringifiedParams}`
        : `/api/feature_flags_staff_cache/`
}

/**
 * Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.
 *
 * Rebuild/clear act on two logical targets: 'evaluation' (the /flags cache) and 'definitions'
 * (the /flags/definitions local-eval cache), independently readable and mutable.
 *
 * Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
 * when a flag changes) rather than re-implementing cache-write logic. Registered on the root
 * router so it is not team-nested; staff act on teams they do not belong to.
 */
export const featureFlagsStaffCacheList = async (
    params: FeatureFlagsStaffCacheListParams,
    options?: RequestInit
): Promise<StaffCacheStatusResponseApi> => {
    return apiMutator<StaffCacheStatusResponseApi>(getFeatureFlagsStaffCacheListUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureFlagsStaffCacheClearCreateUrl = () => {
    return `/api/feature_flags_staff_cache/clear/`
}

/**
 * Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.
 *
 * Rebuild/clear act on two logical targets: 'evaluation' (the /flags cache) and 'definitions'
 * (the /flags/definitions local-eval cache), independently readable and mutable.
 *
 * Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
 * when a flag changes) rather than re-implementing cache-write logic. Registered on the root
 * router so it is not team-nested; staff act on teams they do not belong to.
 */
export const featureFlagsStaffCacheClearCreate = async (
    staffCacheMutationApi: StaffCacheMutationApi,
    options?: RequestInit
): Promise<StaffCacheMutationResponseApi> => {
    return apiMutator<StaffCacheMutationResponseApi>(getFeatureFlagsStaffCacheClearCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(staffCacheMutationApi),
    })
}

export const getFeatureFlagsStaffCacheEntryRetrieveUrl = (params: FeatureFlagsStaffCacheEntryRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/feature_flags_staff_cache/entry/?${stringifiedParams}`
        : `/api/feature_flags_staff_cache/entry/`
}

/**
 * Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.
 *
 * Rebuild/clear act on two logical targets: 'evaluation' (the /flags cache) and 'definitions'
 * (the /flags/definitions local-eval cache), independently readable and mutable.
 *
 * Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
 * when a flag changes) rather than re-implementing cache-write logic. Registered on the root
 * router so it is not team-nested; staff act on teams they do not belong to.
 */
export const featureFlagsStaffCacheEntryRetrieve = async (
    params: FeatureFlagsStaffCacheEntryRetrieveParams,
    options?: RequestInit
): Promise<StaffCacheEntryResponseApi> => {
    return apiMutator<StaffCacheEntryResponseApi>(getFeatureFlagsStaffCacheEntryRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureFlagsStaffCacheRebuildCreateUrl = () => {
    return `/api/feature_flags_staff_cache/rebuild/`
}

/**
 * Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.
 *
 * Rebuild/clear act on two logical targets: 'evaluation' (the /flags cache) and 'definitions'
 * (the /flags/definitions local-eval cache), independently readable and mutable.
 *
 * Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
 * when a flag changes) rather than re-implementing cache-write logic. Registered on the root
 * router so it is not team-nested; staff act on teams they do not belong to.
 */
export const featureFlagsStaffCacheRebuildCreate = async (
    staffCacheMutationApi: StaffCacheMutationApi,
    options?: RequestInit
): Promise<StaffCacheMutationResponseApi> => {
    return apiMutator<StaffCacheMutationResponseApi>(getFeatureFlagsStaffCacheRebuildCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(staffCacheMutationApi),
    })
}

export const getFeatureFlagsStaffTeamsListUrl = (params: FeatureFlagsStaffTeamsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/feature_flags_staff_teams/?${stringifiedParams}`
        : `/api/feature_flags_staff_teams/`
}

/**
 * Staff-only, unscoped team search across every organization.
 *
 * Unlike TeamViewSet (membership-scoped via TeamAndOrgViewSetMixin), staff need to look up
 * teams they do not belong to in order to inspect and rebuild flag caches. Registered on the
 * root router so it is not team-nested. Exposes the same fields Django admin's TeamAdmin
 * already shows staff un-redacted, so no new data exposure.
 */
export const featureFlagsStaffTeamsList = async (
    params: FeatureFlagsStaffTeamsListParams,
    options?: RequestInit
): Promise<StaffTeamSearchResponseApi> => {
    return apiMutator<StaffTeamSearchResponseApi>(getFeatureFlagsStaffTeamsListUrl(params), {
        ...options,
        method: 'GET',
    })
}

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

export const getOrgFeatureFlagsKeysUrl = (organizationId: string, params?: OrgFeatureFlagsKeysParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/feature_flags/keys/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/feature_flags/keys/`
}

/**
 * Paginated, de-duplicated list of feature flag keys across the org's compared projects.
 *
 * Unlike the project-scoped flag list, this enumerates the union of flag keys across every
 * compared project, so flags that exist only in another project still appear as rows.
 */
export const orgFeatureFlagsKeys = async (
    organizationId: string,
    params?: OrgFeatureFlagsKeysParams,
    options?: RequestInit
): Promise<OrganizationFeatureFlagKeysResponseApi> => {
    return apiMutator<OrganizationFeatureFlagKeysResponseApi>(getOrgFeatureFlagsKeysUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getOrganizationsProjectsEvaluationContextSuggestionsCreateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/evaluation_context_suggestions/`
}

/**
 * Hide an evaluation context name from the flag editor's suggestion list, or restore it.
 *
 * POST hides the name; DELETE restores it. The underlying context row and any flags already
 * using it are never modified — this only controls what gets suggested.
 */
export const organizationsProjectsEvaluationContextSuggestionsCreate = async (
    organizationId: string,
    id: number,
    evaluationContextSuggestionRequestApi: EvaluationContextSuggestionRequestApi,
    options?: RequestInit
): Promise<EvaluationContextSuggestionResponseApi> => {
    return apiMutator<EvaluationContextSuggestionResponseApi>(
        getOrganizationsProjectsEvaluationContextSuggestionsCreateUrl(organizationId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(evaluationContextSuggestionRequestApi),
        }
    )
}

export const getOrganizationsProjectsEvaluationContextSuggestionsDestroyUrl = (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsEvaluationContextSuggestionsDestroyParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/${id}/evaluation_context_suggestions/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/${id}/evaluation_context_suggestions/`
}

/**
 * Hide an evaluation context name from the flag editor's suggestion list, or restore it.
 *
 * POST hides the name; DELETE restores it. The underlying context row and any flags already
 * using it are never modified — this only controls what gets suggested.
 */
export const organizationsProjectsEvaluationContextSuggestionsDestroy = async (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsEvaluationContextSuggestionsDestroyParams,
    options?: RequestInit
): Promise<EvaluationContextSuggestionResponseApi> => {
    return apiMutator<EvaluationContextSuggestionResponseApi>(
        getOrganizationsProjectsEvaluationContextSuggestionsDestroyUrl(organizationId, id, params),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export const getEnvironmentsEvaluationContextSuggestionsCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/environments/${id}/evaluation_context_suggestions/`
}

/**
 * Hide an evaluation context name from the flag editor's suggestion list, or restore it.
 *
 * POST hides the name; DELETE restores it. The underlying context row and any flags already
 * using it are never modified — this only controls what gets suggested.
 */
export const environmentsEvaluationContextSuggestionsCreate = async (
    projectId: string,
    id: number,
    evaluationContextSuggestionRequestApi: EvaluationContextSuggestionRequestApi,
    options?: RequestInit
): Promise<EvaluationContextSuggestionResponseApi> => {
    return apiMutator<EvaluationContextSuggestionResponseApi>(
        getEnvironmentsEvaluationContextSuggestionsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(evaluationContextSuggestionRequestApi),
        }
    )
}

export const getEnvironmentsEvaluationContextSuggestionsDestroyUrl = (
    projectId: string,
    id: number,
    params: EnvironmentsEvaluationContextSuggestionsDestroyParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/environments/${id}/evaluation_context_suggestions/?${stringifiedParams}`
        : `/api/projects/${projectId}/environments/${id}/evaluation_context_suggestions/`
}

/**
 * Hide an evaluation context name from the flag editor's suggestion list, or restore it.
 *
 * POST hides the name; DELETE restores it. The underlying context row and any flags already
 * using it are never modified — this only controls what gets suggested.
 */
export const environmentsEvaluationContextSuggestionsDestroy = async (
    projectId: string,
    id: number,
    params: EnvironmentsEvaluationContextSuggestionsDestroyParams,
    options?: RequestInit
): Promise<EvaluationContextSuggestionResponseApi> => {
    return apiMutator<EvaluationContextSuggestionResponseApi>(
        getEnvironmentsEvaluationContextSuggestionsDestroyUrl(projectId, id, params),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export const getFeatureFlagsListUrl = (projectId: string, params?: FeatureFlagsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const featureFlagsCreate = async (
    projectId: string,
    featureFlagCreateRequestSchemaApi?: FeatureFlagCreateRequestSchemaApi,
    options?: RequestInit
): Promise<FeatureFlagApi> => {
    return apiMutator<FeatureFlagApi>(getFeatureFlagsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagCreateRequestSchemaApi),
    })
}

export const getFeatureFlagsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const featureFlagsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedFeatureFlagPartialUpdateRequestSchemaApi?: PatchedFeatureFlagPartialUpdateRequestSchemaApi,
    options?: RequestInit
): Promise<FeatureFlagApi> => {
    return apiMutator<FeatureFlagApi>(getFeatureFlagsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFeatureFlagPartialUpdateRequestSchemaApi),
    })
}

export const getFeatureFlagsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const featureFlagsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getFeatureFlagsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getFeatureFlagsActivityRetrieveUrl = (
    projectId: string,
    id: number,
    params?: FeatureFlagsActivityRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/${id}/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/${id}/activity/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsCreateStaticCohortForFlagCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/create_static_cohort_for_flag/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsDashboardCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/dashboard/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsDependentFlagsListUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/dependent_flags/`
}

/**
 * Get other active flags that depend on this flag.
 */
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

export const getFeatureFlagsEnrichUsageDashboardCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/enrich_usage_dashboard/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsRemoteConfigRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/remote_config/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsStatusRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/status/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsTestEvaluationCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/test_evaluation/`
}

/**
 * Test feature flag evaluation against a specific user at an optional point in time.
 *
 * This endpoint allows testing how a feature flag would evaluate for a specific user,
 * optionally at a historical timestamp. When a timestamp is provided, both the flag
 * conditions and person properties are evaluated as they existed at that time.
 */
export const featureFlagsTestEvaluationCreate = async (
    projectId: string,
    id: number,
    featureFlagTestEvaluationRequestApi?: FeatureFlagTestEvaluationRequestApi,
    options?: RequestInit
): Promise<FeatureFlagTestEvaluationResponseApi> => {
    return apiMutator<FeatureFlagTestEvaluationResponseApi>(getFeatureFlagsTestEvaluationCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureFlagTestEvaluationRequestApi),
    })
}

export const getFeatureFlagsVersionsRetrieveUrl = (projectId: string, id: number, versionNumber: number) => {
    return `/api/projects/${projectId}/feature_flags/${id}/versions/${versionNumber}/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsAllActivityRetrieveUrl = (
    projectId: string,
    params?: FeatureFlagsAllActivityRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/activity/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsBulkDeleteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/bulk_delete/`
}

/**
 * Bulk delete feature flags by filter criteria or explicit IDs.
 *
 * Accepts either:
 * - {"filters": {...}} - Same filter params as list endpoint (search, active, type, etc.)
 * - {"ids": [...]} - Explicit list of flag IDs (no limit)
 *
 * Returns same format as bulk_delete for UI compatibility.
 *
 * Uses bulk operations for efficiency: database updates are batched and cache
 * invalidation happens once at the end rather than per-flag.
 */
export const featureFlagsBulkDeleteCreate = async (
    projectId: string,
    bulkDeleteRequestApi?: BulkDeleteRequestApi,
    options?: RequestInit
): Promise<BulkDeleteResponseApi> => {
    return apiMutator<BulkDeleteResponseApi>(getFeatureFlagsBulkDeleteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkDeleteRequestApi),
    })
}

export const getFeatureFlagsBulkKeysRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/bulk_keys/`
}

/**
 * Get feature flag keys by IDs.
 * Accepts a list of feature flag IDs and returns a mapping of ID to key.
 */
export const featureFlagsBulkKeysRetrieve = async (
    projectId: string,
    bulkKeysRequestApi?: BulkKeysRequestApi,
    options?: RequestInit
): Promise<BulkKeysResponseApi> => {
    return apiMutator<BulkKeysResponseApi>(getFeatureFlagsBulkKeysRetrieveUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkKeysRequestApi),
    })
}

export const getFeatureFlagsBulkUpdateTagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/bulk_update_tags/`
}

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
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

export const getFeatureFlagsEvaluationReasonsRetrieveUrl = (
    projectId: string,
    params: FeatureFlagsEvaluationReasonsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/evaluation_reasons/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/evaluation_reasons/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsMatchingIdsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/matching_ids/`
}

/**
 * Get IDs of all feature flags matching the current filters.
 * Uses the same filtering logic as the list endpoint.
 * Returns only IDs that the user has permission to edit.
 */
export const featureFlagsMatchingIdsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFeatureFlagsMatchingIdsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureFlagsMyFlagsRetrieveUrl = (projectId: string, params?: FeatureFlagsMyFlagsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/my_flags/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/my_flags/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFeatureFlagsUserBlastRadiusCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_flags/user_blast_radius/`
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const getFlagValueValuesRetrieveUrl = (projectId: string, params?: FlagValueValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/flag_value/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/flag_value/values/`
}

/**
 * Get possible values for a feature flag.
 *
 * Query parameters:
 * - key: The flag ID (required)
 * Returns:
 *
 * - Array of objects with 'name' field containing possible values
 */
export const flagValueValuesRetrieve = async (
    projectId: string,
    params?: FlagValueValuesRetrieveParams,
    options?: RequestInit
): Promise<FlagValueResponseApi> => {
    return apiMutator<FlagValueResponseApi>(getFlagValueValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getScheduledChangesListUrl = (projectId: string, params?: ScheduledChangesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/scheduled_changes/?${stringifiedParams}`
        : `/api/projects/${projectId}/scheduled_changes/`
}

/**
 * Create, read, update and delete scheduled changes.
 */
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

export const getScheduledChangesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/scheduled_changes/`
}

/**
 * Create, read, update and delete scheduled changes.
 */
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

export const getScheduledChangesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

/**
 * Create, read, update and delete scheduled changes.
 */
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

export const getScheduledChangesUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

/**
 * Create, read, update and delete scheduled changes.
 */
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

export const getScheduledChangesPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const scheduledChangesPartialUpdate = async (
    projectId: string,
    id: number,
    patchedScheduledChangeApi?: NonReadonly<PatchedScheduledChangeApi>,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedScheduledChangeApi),
    })
}

export const getScheduledChangesDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const scheduledChangesDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getScheduledChangesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
