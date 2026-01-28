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
    ErrorTrackingAssignmentRuleApi,
    ErrorTrackingAssignmentRulesListParams,
    ErrorTrackingExternalReferenceApi,
    ErrorTrackingExternalReferencesListParams,
    ErrorTrackingFingerprintApi,
    ErrorTrackingFingerprintsListParams,
    ErrorTrackingGroupingRuleApi,
    ErrorTrackingGroupingRulesListParams,
    ErrorTrackingIssueFullApi,
    ErrorTrackingIssuesListParams,
    ErrorTrackingReleaseApi,
    ErrorTrackingReleasesList2Params,
    ErrorTrackingReleasesListParams,
    ErrorTrackingStackFrameApi,
    ErrorTrackingStackFramesListParams,
    ErrorTrackingSuppressionRuleApi,
    ErrorTrackingSuppressionRulesListParams,
    ErrorTrackingSymbolSetApi,
    ErrorTrackingSymbolSetsList2Params,
    ErrorTrackingSymbolSetsListParams,
    PaginatedErrorTrackingAssignmentRuleListApi,
    PaginatedErrorTrackingExternalReferenceListApi,
    PaginatedErrorTrackingFingerprintListApi,
    PaginatedErrorTrackingGroupingRuleListApi,
    PaginatedErrorTrackingIssueFullListApi,
    PaginatedErrorTrackingReleaseListApi,
    PaginatedErrorTrackingStackFrameListApi,
    PaginatedErrorTrackingSuppressionRuleListApi,
    PaginatedErrorTrackingSymbolSetListApi,
    PatchedErrorTrackingAssignmentRuleApi,
    PatchedErrorTrackingExternalReferenceApi,
    PatchedErrorTrackingGroupingRuleApi,
    PatchedErrorTrackingIssueFullApi,
    PatchedErrorTrackingReleaseApi,
    PatchedErrorTrackingSuppressionRuleApi,
    PatchedErrorTrackingSymbolSetApi,
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

export const getErrorTrackingAssignmentRulesListUrl = (
    projectId: string,
    params?: ErrorTrackingAssignmentRulesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/assignment_rules/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/assignment_rules/`
}

export const errorTrackingAssignmentRulesList = async (
    projectId: string,
    params?: ErrorTrackingAssignmentRulesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingAssignmentRuleListApi> => {
    return apiMutator<PaginatedErrorTrackingAssignmentRuleListApi>(
        getErrorTrackingAssignmentRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getErrorTrackingAssignmentRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/`
}

export const errorTrackingAssignmentRulesCreate = async (
    projectId: string,
    errorTrackingAssignmentRuleApi: NonReadonly<ErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingAssignmentRuleApi> => {
    return apiMutator<ErrorTrackingAssignmentRuleApi>(getErrorTrackingAssignmentRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingAssignmentRuleApi),
    })
}

export const getErrorTrackingAssignmentRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const errorTrackingAssignmentRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingAssignmentRuleApi> => {
    return apiMutator<ErrorTrackingAssignmentRuleApi>(getErrorTrackingAssignmentRulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingAssignmentRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const errorTrackingAssignmentRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingAssignmentRuleApi: NonReadonly<ErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingAssignmentRuleApi> => {
    return apiMutator<ErrorTrackingAssignmentRuleApi>(getErrorTrackingAssignmentRulesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingAssignmentRuleApi),
    })
}

export const getErrorTrackingAssignmentRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const errorTrackingAssignmentRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingAssignmentRuleApi: NonReadonly<PatchedErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingAssignmentRuleApi> => {
    return apiMutator<ErrorTrackingAssignmentRuleApi>(getErrorTrackingAssignmentRulesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingAssignmentRuleApi),
    })
}

export const getErrorTrackingAssignmentRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const errorTrackingAssignmentRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingAssignmentRulesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingAssignmentRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/reorder/`
}

export const errorTrackingAssignmentRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingAssignmentRuleApi: NonReadonly<PatchedErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingAssignmentRulesReorderPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingAssignmentRuleApi),
    })
}

export const getErrorTrackingExternalReferencesListUrl = (
    projectId: string,
    params?: ErrorTrackingExternalReferencesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/external_references/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/external_references/`
}

export const errorTrackingExternalReferencesList = async (
    projectId: string,
    params?: ErrorTrackingExternalReferencesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingExternalReferenceListApi> => {
    return apiMutator<PaginatedErrorTrackingExternalReferenceListApi>(
        getErrorTrackingExternalReferencesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getErrorTrackingExternalReferencesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/`
}

export const errorTrackingExternalReferencesCreate = async (
    projectId: string,
    errorTrackingExternalReferenceApi: NonReadonly<ErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<ErrorTrackingExternalReferenceApi> => {
    return apiMutator<ErrorTrackingExternalReferenceApi>(getErrorTrackingExternalReferencesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingExternalReferenceApi),
    })
}

export const getErrorTrackingExternalReferencesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const errorTrackingExternalReferencesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingExternalReferenceApi> => {
    return apiMutator<ErrorTrackingExternalReferenceApi>(getErrorTrackingExternalReferencesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingExternalReferencesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const errorTrackingExternalReferencesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingExternalReferenceApi: NonReadonly<ErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<ErrorTrackingExternalReferenceApi> => {
    return apiMutator<ErrorTrackingExternalReferenceApi>(getErrorTrackingExternalReferencesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingExternalReferenceApi),
    })
}

export const getErrorTrackingExternalReferencesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const errorTrackingExternalReferencesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingExternalReferenceApi: NonReadonly<PatchedErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<ErrorTrackingExternalReferenceApi> => {
    return apiMutator<ErrorTrackingExternalReferenceApi>(
        getErrorTrackingExternalReferencesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingExternalReferenceApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getErrorTrackingExternalReferencesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const errorTrackingExternalReferencesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getErrorTrackingExternalReferencesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingFingerprintsListUrl = (
    projectId: string,
    params?: ErrorTrackingFingerprintsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/fingerprints/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/fingerprints/`
}

export const errorTrackingFingerprintsList = async (
    projectId: string,
    params?: ErrorTrackingFingerprintsListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingFingerprintListApi> => {
    return apiMutator<PaginatedErrorTrackingFingerprintListApi>(
        getErrorTrackingFingerprintsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getErrorTrackingFingerprintsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/fingerprints/${id}/`
}

export const errorTrackingFingerprintsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingFingerprintApi> => {
    return apiMutator<ErrorTrackingFingerprintApi>(getErrorTrackingFingerprintsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getErrorTrackingFingerprintsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/fingerprints/${id}/`
}

export const errorTrackingFingerprintsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getErrorTrackingFingerprintsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingGitProviderFileLinksResolveGithubRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/git-provider-file-links/resolve_github/`
}

export const errorTrackingGitProviderFileLinksResolveGithubRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingGitProviderFileLinksResolveGithubRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingGitProviderFileLinksResolveGitlabRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/git-provider-file-links/resolve_gitlab/`
}

export const errorTrackingGitProviderFileLinksResolveGitlabRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingGitProviderFileLinksResolveGitlabRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingGroupingRulesListUrl = (
    projectId: string,
    params?: ErrorTrackingGroupingRulesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/grouping_rules/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/grouping_rules/`
}

export const errorTrackingGroupingRulesList = async (
    projectId: string,
    params?: ErrorTrackingGroupingRulesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingGroupingRuleListApi> => {
    return apiMutator<PaginatedErrorTrackingGroupingRuleListApi>(
        getErrorTrackingGroupingRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getErrorTrackingGroupingRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/`
}

export const errorTrackingGroupingRulesCreate = async (
    projectId: string,
    errorTrackingGroupingRuleApi: NonReadonly<ErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingGroupingRuleApi> => {
    return apiMutator<ErrorTrackingGroupingRuleApi>(getErrorTrackingGroupingRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingGroupingRuleApi),
    })
}

export const getErrorTrackingGroupingRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const errorTrackingGroupingRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingGroupingRuleApi> => {
    return apiMutator<ErrorTrackingGroupingRuleApi>(getErrorTrackingGroupingRulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingGroupingRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const errorTrackingGroupingRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingGroupingRuleApi: NonReadonly<ErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingGroupingRuleApi> => {
    return apiMutator<ErrorTrackingGroupingRuleApi>(getErrorTrackingGroupingRulesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingGroupingRuleApi),
    })
}

export const getErrorTrackingGroupingRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const errorTrackingGroupingRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingGroupingRuleApi: NonReadonly<PatchedErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingGroupingRuleApi> => {
    return apiMutator<ErrorTrackingGroupingRuleApi>(getErrorTrackingGroupingRulesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingGroupingRuleApi),
    })
}

export const getErrorTrackingGroupingRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const errorTrackingGroupingRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingGroupingRulesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingGroupingRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/reorder/`
}

export const errorTrackingGroupingRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingGroupingRuleApi: NonReadonly<PatchedErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingGroupingRulesReorderPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingGroupingRuleApi),
    })
}

export const getErrorTrackingIssuesListUrl = (projectId: string, params?: ErrorTrackingIssuesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/issues/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/issues/`
}

export const errorTrackingIssuesList = async (
    projectId: string,
    params?: ErrorTrackingIssuesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingIssueFullListApi> => {
    return apiMutator<PaginatedErrorTrackingIssueFullListApi>(getErrorTrackingIssuesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingIssuesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/`
}

export const errorTrackingIssuesCreate = async (
    projectId: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<ErrorTrackingIssueFullApi> => {
    return apiMutator<ErrorTrackingIssueFullApi>(getErrorTrackingIssuesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getErrorTrackingIssuesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const errorTrackingIssuesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingIssueFullApi> => {
    return apiMutator<ErrorTrackingIssueFullApi>(getErrorTrackingIssuesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingIssuesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const errorTrackingIssuesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<ErrorTrackingIssueFullApi> => {
    return apiMutator<ErrorTrackingIssueFullApi>(getErrorTrackingIssuesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getErrorTrackingIssuesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const errorTrackingIssuesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingIssueFullApi: NonReadonly<PatchedErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<ErrorTrackingIssueFullApi> => {
    return apiMutator<ErrorTrackingIssueFullApi>(getErrorTrackingIssuesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingIssueFullApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getErrorTrackingIssuesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const errorTrackingIssuesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getErrorTrackingIssuesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingIssuesActivityRetrieve2Url = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/activity/`
}

export const errorTrackingIssuesActivityRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingIssuesActivityRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingIssuesAssignPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/assign/`
}

export const errorTrackingIssuesAssignPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingIssueFullApi: NonReadonly<PatchedErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingIssuesAssignPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingIssueFullApi),
    })
}

export const getErrorTrackingIssuesCohortUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/cohort/`
}

export const errorTrackingIssuesCohortUpdate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingIssuesCohortUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getErrorTrackingIssuesMergeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/merge/`
}

export const errorTrackingIssuesMergeCreate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingIssuesMergeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getErrorTrackingIssuesSplitCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/split/`
}

export const errorTrackingIssuesSplitCreate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingIssuesSplitCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getErrorTrackingIssuesActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/activity/`
}

export const errorTrackingIssuesActivityRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getErrorTrackingIssuesActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingIssuesBulkCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/bulk/`
}

export const errorTrackingIssuesBulkCreate = async (
    projectId: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingIssuesBulkCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getErrorTrackingIssuesValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/values/`
}

export const errorTrackingIssuesValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getErrorTrackingIssuesValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingReleasesListUrl = (projectId: string, params?: ErrorTrackingReleasesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/releases/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/releases/`
}

export const errorTrackingReleasesList = async (
    projectId: string,
    params?: ErrorTrackingReleasesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingReleaseListApi> => {
    return apiMutator<PaginatedErrorTrackingReleaseListApi>(getErrorTrackingReleasesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingReleasesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/`
}

export const errorTrackingReleasesCreate = async (
    projectId: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getErrorTrackingReleasesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export const getErrorTrackingReleasesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getErrorTrackingReleasesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingReleasesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getErrorTrackingReleasesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export const getErrorTrackingReleasesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingReleaseApi: NonReadonly<PatchedErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getErrorTrackingReleasesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingReleaseApi),
    })
}

export const getErrorTrackingReleasesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingReleasesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingReleasesHashRetrieveUrl = (projectId: string, hashId: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/hash/${hashId}/`
}

export const errorTrackingReleasesHashRetrieve = async (
    projectId: string,
    hashId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingReleasesHashRetrieveUrl(projectId, hashId), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingStackFramesListUrl = (projectId: string, params?: ErrorTrackingStackFramesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/stack_frames/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/stack_frames/`
}

export const errorTrackingStackFramesList = async (
    projectId: string,
    params?: ErrorTrackingStackFramesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingStackFrameListApi> => {
    return apiMutator<PaginatedErrorTrackingStackFrameListApi>(getErrorTrackingStackFramesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingStackFramesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/${id}/`
}

export const errorTrackingStackFramesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingStackFrameApi> => {
    return apiMutator<ErrorTrackingStackFrameApi>(getErrorTrackingStackFramesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getErrorTrackingStackFramesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/${id}/`
}

export const errorTrackingStackFramesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getErrorTrackingStackFramesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingStackFramesBatchGetCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/batch_get/`
}

export const errorTrackingStackFramesBatchGetCreate = async (
    projectId: string,
    errorTrackingStackFrameApi: NonReadonly<ErrorTrackingStackFrameApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingStackFramesBatchGetCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingStackFrameApi),
    })
}

export const getErrorTrackingSuppressionRulesListUrl = (
    projectId: string,
    params?: ErrorTrackingSuppressionRulesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/suppression_rules/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/suppression_rules/`
}

export const errorTrackingSuppressionRulesList = async (
    projectId: string,
    params?: ErrorTrackingSuppressionRulesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingSuppressionRuleListApi> => {
    return apiMutator<PaginatedErrorTrackingSuppressionRuleListApi>(
        getErrorTrackingSuppressionRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getErrorTrackingSuppressionRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/`
}

export const errorTrackingSuppressionRulesCreate = async (
    projectId: string,
    errorTrackingSuppressionRuleApi: NonReadonly<ErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingSuppressionRuleApi> => {
    return apiMutator<ErrorTrackingSuppressionRuleApi>(getErrorTrackingSuppressionRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSuppressionRuleApi),
    })
}

export const getErrorTrackingSuppressionRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const errorTrackingSuppressionRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingSuppressionRuleApi> => {
    return apiMutator<ErrorTrackingSuppressionRuleApi>(getErrorTrackingSuppressionRulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingSuppressionRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const errorTrackingSuppressionRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSuppressionRuleApi: NonReadonly<ErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingSuppressionRuleApi> => {
    return apiMutator<ErrorTrackingSuppressionRuleApi>(getErrorTrackingSuppressionRulesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSuppressionRuleApi),
    })
}

export const getErrorTrackingSuppressionRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const errorTrackingSuppressionRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingSuppressionRuleApi: NonReadonly<PatchedErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingSuppressionRuleApi> => {
    return apiMutator<ErrorTrackingSuppressionRuleApi>(
        getErrorTrackingSuppressionRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingSuppressionRuleApi),
        }
    )
}

export const getErrorTrackingSuppressionRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const errorTrackingSuppressionRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSuppressionRulesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingSuppressionRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/reorder/`
}

export const errorTrackingSuppressionRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingSuppressionRuleApi: NonReadonly<PatchedErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSuppressionRulesReorderPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingSuppressionRuleApi),
    })
}

export const getErrorTrackingSymbolSetsListUrl = (projectId: string, params?: ErrorTrackingSymbolSetsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/symbol_sets/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/symbol_sets/`
}

export const errorTrackingSymbolSetsList = async (
    projectId: string,
    params?: ErrorTrackingSymbolSetsListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingSymbolSetListApi> => {
    return apiMutator<PaginatedErrorTrackingSymbolSetListApi>(getErrorTrackingSymbolSetsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingSymbolSetsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/`
}

export const errorTrackingSymbolSetsCreate = async (
    projectId: string,
    errorTrackingSymbolSetsCreateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getErrorTrackingSymbolSetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(errorTrackingSymbolSetsCreateBody),
    })
}

export const getErrorTrackingSymbolSetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getErrorTrackingSymbolSetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingSymbolSetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetsUpdateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getErrorTrackingSymbolSetsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        body: JSON.stringify(errorTrackingSymbolSetsUpdateBody),
    })
}

export const getErrorTrackingSymbolSetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsPartialUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetsPartialUpdateBody: NonReadonly<PatchedErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getErrorTrackingSymbolSetsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        body: JSON.stringify(errorTrackingSymbolSetsPartialUpdateBody),
    })
}

export const getErrorTrackingSymbolSetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingSymbolSetsFinishUploadUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/finish_upload/`
}

export const errorTrackingSymbolSetsFinishUploadUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsFinishUploadUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getErrorTrackingSymbolSetsBulkFinishUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/bulk_finish_upload/`
}

export const errorTrackingSymbolSetsBulkFinishUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsBulkFinishUploadCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getErrorTrackingSymbolSetsBulkStartUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/bulk_start_upload/`
}

export const errorTrackingSymbolSetsBulkStartUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsBulkStartUploadCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getErrorTrackingSymbolSetsStartUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/start_upload/`
}

export const errorTrackingSymbolSetsStartUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetsStartUploadCreateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsStartUploadCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(errorTrackingSymbolSetsStartUploadCreateBody),
    })
}

export const getErrorTrackingReleasesList2Url = (projectId: string, params?: ErrorTrackingReleasesList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/error_tracking/releases/?${stringifiedParams}`
        : `/api/projects/${projectId}/error_tracking/releases/`
}

export const errorTrackingReleasesList2 = async (
    projectId: string,
    params?: ErrorTrackingReleasesList2Params,
    options?: RequestInit
): Promise<PaginatedErrorTrackingReleaseListApi> => {
    return apiMutator<PaginatedErrorTrackingReleaseListApi>(getErrorTrackingReleasesList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingReleasesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/`
}

export const errorTrackingReleasesCreate2 = async (
    projectId: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getErrorTrackingReleasesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export const getErrorTrackingReleasesRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getErrorTrackingReleasesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingReleasesUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesUpdate2 = async (
    projectId: string,
    id: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getErrorTrackingReleasesUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export const getErrorTrackingReleasesPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedErrorTrackingReleaseApi: NonReadonly<PatchedErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getErrorTrackingReleasesPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingReleaseApi),
    })
}

export const getErrorTrackingReleasesDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingReleasesDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingReleasesHashRetrieve2Url = (projectId: string, hashId: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/hash/${hashId}/`
}

export const errorTrackingReleasesHashRetrieve2 = async (
    projectId: string,
    hashId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingReleasesHashRetrieve2Url(projectId, hashId), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingSymbolSetsList2Url = (projectId: string, params?: ErrorTrackingSymbolSetsList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/error_tracking/symbol_sets/?${stringifiedParams}`
        : `/api/projects/${projectId}/error_tracking/symbol_sets/`
}

export const errorTrackingSymbolSetsList2 = async (
    projectId: string,
    params?: ErrorTrackingSymbolSetsList2Params,
    options?: RequestInit
): Promise<PaginatedErrorTrackingSymbolSetListApi> => {
    return apiMutator<PaginatedErrorTrackingSymbolSetListApi>(getErrorTrackingSymbolSetsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingSymbolSetsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/`
}

export const errorTrackingSymbolSetsCreate2 = async (
    projectId: string,
    errorTrackingSymbolSetsCreate2Body: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getErrorTrackingSymbolSetsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(errorTrackingSymbolSetsCreate2Body),
    })
}

export const getErrorTrackingSymbolSetsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getErrorTrackingSymbolSetsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getErrorTrackingSymbolSetsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsUpdate2 = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetsUpdate2Body: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getErrorTrackingSymbolSetsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        body: JSON.stringify(errorTrackingSymbolSetsUpdate2Body),
    })
}

export const getErrorTrackingSymbolSetsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsPartialUpdate2 = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetsPartialUpdate2Body: NonReadonly<PatchedErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getErrorTrackingSymbolSetsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        body: JSON.stringify(errorTrackingSymbolSetsPartialUpdate2Body),
    })
}

export const getErrorTrackingSymbolSetsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getErrorTrackingSymbolSetsFinishUploadUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/finish_upload/`
}

export const errorTrackingSymbolSetsFinishUploadUpdate2 = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsFinishUploadUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getErrorTrackingSymbolSetsBulkFinishUploadCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/bulk_finish_upload/`
}

export const errorTrackingSymbolSetsBulkFinishUploadCreate2 = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsBulkFinishUploadCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getErrorTrackingSymbolSetsBulkStartUploadCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/bulk_start_upload/`
}

export const errorTrackingSymbolSetsBulkStartUploadCreate2 = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsBulkStartUploadCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getErrorTrackingSymbolSetsStartUploadCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/start_upload/`
}

export const errorTrackingSymbolSetsStartUploadCreate2 = async (
    projectId: string,
    errorTrackingSymbolSetsStartUploadCreate2Body: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getErrorTrackingSymbolSetsStartUploadCreate2Url(projectId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(errorTrackingSymbolSetsStartUploadCreate2Body),
    })
}
