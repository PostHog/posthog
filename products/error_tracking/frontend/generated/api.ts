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
    EnvironmentsErrorTrackingAssignmentRulesListParams,
    EnvironmentsErrorTrackingExternalReferencesListParams,
    EnvironmentsErrorTrackingFingerprintsListParams,
    EnvironmentsErrorTrackingGroupingRulesListParams,
    EnvironmentsErrorTrackingIssuesListParams,
    EnvironmentsErrorTrackingReleasesListParams,
    EnvironmentsErrorTrackingStackFramesListParams,
    EnvironmentsErrorTrackingSuppressionRulesListParams,
    EnvironmentsErrorTrackingSymbolSetsListParams,
    ErrorTrackingAssignmentRuleApi,
    ErrorTrackingExternalReferenceApi,
    ErrorTrackingFingerprintApi,
    ErrorTrackingGroupingRuleApi,
    ErrorTrackingIssueFullApi,
    ErrorTrackingReleaseApi,
    ErrorTrackingReleasesListParams,
    ErrorTrackingStackFrameApi,
    ErrorTrackingSuppressionRuleApi,
    ErrorTrackingSymbolSetApi,
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

export const getEnvironmentsErrorTrackingAssignmentRulesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingAssignmentRulesListParams
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

export const environmentsErrorTrackingAssignmentRulesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingAssignmentRulesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingAssignmentRuleListApi> => {
    return apiMutator<PaginatedErrorTrackingAssignmentRuleListApi>(
        getEnvironmentsErrorTrackingAssignmentRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingAssignmentRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/`
}

export const environmentsErrorTrackingAssignmentRulesCreate = async (
    projectId: string,
    errorTrackingAssignmentRuleApi: NonReadonly<ErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingAssignmentRuleApi> => {
    return apiMutator<ErrorTrackingAssignmentRuleApi>(getEnvironmentsErrorTrackingAssignmentRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingAssignmentRuleApi),
    })
}

export const getEnvironmentsErrorTrackingAssignmentRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const environmentsErrorTrackingAssignmentRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingAssignmentRuleApi> => {
    return apiMutator<ErrorTrackingAssignmentRuleApi>(
        getEnvironmentsErrorTrackingAssignmentRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingAssignmentRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const environmentsErrorTrackingAssignmentRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingAssignmentRuleApi: NonReadonly<ErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingAssignmentRuleApi> => {
    return apiMutator<ErrorTrackingAssignmentRuleApi>(
        getEnvironmentsErrorTrackingAssignmentRulesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingAssignmentRuleApi),
        }
    )
}

export const getEnvironmentsErrorTrackingAssignmentRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const environmentsErrorTrackingAssignmentRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingAssignmentRuleApi: NonReadonly<PatchedErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingAssignmentRuleApi> => {
    return apiMutator<ErrorTrackingAssignmentRuleApi>(
        getEnvironmentsErrorTrackingAssignmentRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingAssignmentRuleApi),
        }
    )
}

export const getEnvironmentsErrorTrackingAssignmentRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const environmentsErrorTrackingAssignmentRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingAssignmentRulesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingAssignmentRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/reorder/`
}

export const environmentsErrorTrackingAssignmentRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingAssignmentRuleApi: NonReadonly<PatchedErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingAssignmentRulesReorderPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingAssignmentRuleApi),
    })
}

export const getEnvironmentsErrorTrackingExternalReferencesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingExternalReferencesListParams
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

export const environmentsErrorTrackingExternalReferencesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingExternalReferencesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingExternalReferenceListApi> => {
    return apiMutator<PaginatedErrorTrackingExternalReferenceListApi>(
        getEnvironmentsErrorTrackingExternalReferencesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingExternalReferencesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/`
}

export const environmentsErrorTrackingExternalReferencesCreate = async (
    projectId: string,
    errorTrackingExternalReferenceApi: NonReadonly<ErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<ErrorTrackingExternalReferenceApi> => {
    return apiMutator<ErrorTrackingExternalReferenceApi>(
        getEnvironmentsErrorTrackingExternalReferencesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingExternalReferenceApi),
        }
    )
}

export const getEnvironmentsErrorTrackingExternalReferencesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const environmentsErrorTrackingExternalReferencesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingExternalReferenceApi> => {
    return apiMutator<ErrorTrackingExternalReferenceApi>(
        getEnvironmentsErrorTrackingExternalReferencesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingExternalReferencesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const environmentsErrorTrackingExternalReferencesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingExternalReferenceApi: NonReadonly<ErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<ErrorTrackingExternalReferenceApi> => {
    return apiMutator<ErrorTrackingExternalReferenceApi>(
        getEnvironmentsErrorTrackingExternalReferencesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingExternalReferenceApi),
        }
    )
}

export const getEnvironmentsErrorTrackingExternalReferencesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const environmentsErrorTrackingExternalReferencesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingExternalReferenceApi: NonReadonly<PatchedErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<ErrorTrackingExternalReferenceApi> => {
    return apiMutator<ErrorTrackingExternalReferenceApi>(
        getEnvironmentsErrorTrackingExternalReferencesPartialUpdateUrl(projectId, id),
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
export const getEnvironmentsErrorTrackingExternalReferencesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const environmentsErrorTrackingExternalReferencesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getEnvironmentsErrorTrackingExternalReferencesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingFingerprintsListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingFingerprintsListParams
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

export const environmentsErrorTrackingFingerprintsList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingFingerprintsListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingFingerprintListApi> => {
    return apiMutator<PaginatedErrorTrackingFingerprintListApi>(
        getEnvironmentsErrorTrackingFingerprintsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingFingerprintsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/fingerprints/${id}/`
}

export const environmentsErrorTrackingFingerprintsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingFingerprintApi> => {
    return apiMutator<ErrorTrackingFingerprintApi>(getEnvironmentsErrorTrackingFingerprintsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getEnvironmentsErrorTrackingFingerprintsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/fingerprints/${id}/`
}

export const environmentsErrorTrackingFingerprintsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getEnvironmentsErrorTrackingFingerprintsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/git-provider-file-links/resolve_github/`
}

export const environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/git-provider-file-links/resolve_gitlab/`
}

export const environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingGroupingRulesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingGroupingRulesListParams
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

export const environmentsErrorTrackingGroupingRulesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingGroupingRulesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingGroupingRuleListApi> => {
    return apiMutator<PaginatedErrorTrackingGroupingRuleListApi>(
        getEnvironmentsErrorTrackingGroupingRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingGroupingRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/`
}

export const environmentsErrorTrackingGroupingRulesCreate = async (
    projectId: string,
    errorTrackingGroupingRuleApi: NonReadonly<ErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingGroupingRuleApi> => {
    return apiMutator<ErrorTrackingGroupingRuleApi>(getEnvironmentsErrorTrackingGroupingRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingGroupingRuleApi),
    })
}

export const getEnvironmentsErrorTrackingGroupingRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const environmentsErrorTrackingGroupingRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingGroupingRuleApi> => {
    return apiMutator<ErrorTrackingGroupingRuleApi>(
        getEnvironmentsErrorTrackingGroupingRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingGroupingRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const environmentsErrorTrackingGroupingRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingGroupingRuleApi: NonReadonly<ErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingGroupingRuleApi> => {
    return apiMutator<ErrorTrackingGroupingRuleApi>(getEnvironmentsErrorTrackingGroupingRulesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingGroupingRuleApi),
    })
}

export const getEnvironmentsErrorTrackingGroupingRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const environmentsErrorTrackingGroupingRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingGroupingRuleApi: NonReadonly<PatchedErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingGroupingRuleApi> => {
    return apiMutator<ErrorTrackingGroupingRuleApi>(
        getEnvironmentsErrorTrackingGroupingRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingGroupingRuleApi),
        }
    )
}

export const getEnvironmentsErrorTrackingGroupingRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const environmentsErrorTrackingGroupingRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingGroupingRulesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingGroupingRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/reorder/`
}

export const environmentsErrorTrackingGroupingRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingGroupingRuleApi: NonReadonly<PatchedErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingGroupingRulesReorderPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingGroupingRuleApi),
    })
}

export const getEnvironmentsErrorTrackingIssuesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingIssuesListParams
) => {
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

export const environmentsErrorTrackingIssuesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingIssuesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingIssueFullListApi> => {
    return apiMutator<PaginatedErrorTrackingIssueFullListApi>(
        getEnvironmentsErrorTrackingIssuesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingIssuesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/`
}

export const environmentsErrorTrackingIssuesCreate = async (
    projectId: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<ErrorTrackingIssueFullApi> => {
    return apiMutator<ErrorTrackingIssueFullApi>(getEnvironmentsErrorTrackingIssuesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getEnvironmentsErrorTrackingIssuesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const environmentsErrorTrackingIssuesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingIssueFullApi> => {
    return apiMutator<ErrorTrackingIssueFullApi>(getEnvironmentsErrorTrackingIssuesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingIssuesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const environmentsErrorTrackingIssuesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<ErrorTrackingIssueFullApi> => {
    return apiMutator<ErrorTrackingIssueFullApi>(getEnvironmentsErrorTrackingIssuesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getEnvironmentsErrorTrackingIssuesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const environmentsErrorTrackingIssuesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingIssueFullApi: NonReadonly<PatchedErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<ErrorTrackingIssueFullApi> => {
    return apiMutator<ErrorTrackingIssueFullApi>(getEnvironmentsErrorTrackingIssuesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingIssueFullApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getEnvironmentsErrorTrackingIssuesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const environmentsErrorTrackingIssuesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getEnvironmentsErrorTrackingIssuesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingIssuesActivityRetrieve2Url = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/activity/`
}

export const environmentsErrorTrackingIssuesActivityRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingIssuesActivityRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingIssuesAssignPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/assign/`
}

export const environmentsErrorTrackingIssuesAssignPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingIssueFullApi: NonReadonly<PatchedErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingIssuesAssignPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingIssueFullApi),
    })
}

export const getEnvironmentsErrorTrackingIssuesCohortUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/cohort/`
}

export const environmentsErrorTrackingIssuesCohortUpdate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingIssuesCohortUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getEnvironmentsErrorTrackingIssuesMergeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/merge/`
}

export const environmentsErrorTrackingIssuesMergeCreate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingIssuesMergeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getEnvironmentsErrorTrackingIssuesSplitCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/split/`
}

export const environmentsErrorTrackingIssuesSplitCreate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingIssuesSplitCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getEnvironmentsErrorTrackingIssuesActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/activity/`
}

export const environmentsErrorTrackingIssuesActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingIssuesActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingIssuesBulkCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/bulk/`
}

export const environmentsErrorTrackingIssuesBulkCreate = async (
    projectId: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingIssuesBulkCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export const getEnvironmentsErrorTrackingIssuesValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/values/`
}

export const environmentsErrorTrackingIssuesValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingIssuesValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingReleasesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingReleasesListParams
) => {
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

export const environmentsErrorTrackingReleasesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingReleasesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingReleaseListApi> => {
    return apiMutator<PaginatedErrorTrackingReleaseListApi>(
        getEnvironmentsErrorTrackingReleasesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingReleasesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/`
}

export const environmentsErrorTrackingReleasesCreate = async (
    projectId: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getEnvironmentsErrorTrackingReleasesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export const getEnvironmentsErrorTrackingReleasesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const environmentsErrorTrackingReleasesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getEnvironmentsErrorTrackingReleasesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingReleasesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const environmentsErrorTrackingReleasesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getEnvironmentsErrorTrackingReleasesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export const getEnvironmentsErrorTrackingReleasesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const environmentsErrorTrackingReleasesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingReleaseApi: NonReadonly<PatchedErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<ErrorTrackingReleaseApi> => {
    return apiMutator<ErrorTrackingReleaseApi>(getEnvironmentsErrorTrackingReleasesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingReleaseApi),
    })
}

export const getEnvironmentsErrorTrackingReleasesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const environmentsErrorTrackingReleasesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingReleasesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingReleasesHashRetrieveUrl = (projectId: string, hashId: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/hash/${hashId}/`
}

export const environmentsErrorTrackingReleasesHashRetrieve = async (
    projectId: string,
    hashId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingReleasesHashRetrieveUrl(projectId, hashId), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingStackFramesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingStackFramesListParams
) => {
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

export const environmentsErrorTrackingStackFramesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingStackFramesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingStackFrameListApi> => {
    return apiMutator<PaginatedErrorTrackingStackFrameListApi>(
        getEnvironmentsErrorTrackingStackFramesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingStackFramesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/${id}/`
}

export const environmentsErrorTrackingStackFramesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingStackFrameApi> => {
    return apiMutator<ErrorTrackingStackFrameApi>(getEnvironmentsErrorTrackingStackFramesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getEnvironmentsErrorTrackingStackFramesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/${id}/`
}

export const environmentsErrorTrackingStackFramesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getEnvironmentsErrorTrackingStackFramesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingStackFramesBatchGetCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/batch_get/`
}

export const environmentsErrorTrackingStackFramesBatchGetCreate = async (
    projectId: string,
    errorTrackingStackFrameApi: NonReadonly<ErrorTrackingStackFrameApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingStackFramesBatchGetCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingStackFrameApi),
    })
}

export const getEnvironmentsErrorTrackingSuppressionRulesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingSuppressionRulesListParams
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

export const environmentsErrorTrackingSuppressionRulesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingSuppressionRulesListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingSuppressionRuleListApi> => {
    return apiMutator<PaginatedErrorTrackingSuppressionRuleListApi>(
        getEnvironmentsErrorTrackingSuppressionRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingSuppressionRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/`
}

export const environmentsErrorTrackingSuppressionRulesCreate = async (
    projectId: string,
    errorTrackingSuppressionRuleApi: NonReadonly<ErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingSuppressionRuleApi> => {
    return apiMutator<ErrorTrackingSuppressionRuleApi>(
        getEnvironmentsErrorTrackingSuppressionRulesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSuppressionRuleApi),
        }
    )
}

export const getEnvironmentsErrorTrackingSuppressionRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const environmentsErrorTrackingSuppressionRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingSuppressionRuleApi> => {
    return apiMutator<ErrorTrackingSuppressionRuleApi>(
        getEnvironmentsErrorTrackingSuppressionRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingSuppressionRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const environmentsErrorTrackingSuppressionRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSuppressionRuleApi: NonReadonly<ErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingSuppressionRuleApi> => {
    return apiMutator<ErrorTrackingSuppressionRuleApi>(
        getEnvironmentsErrorTrackingSuppressionRulesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSuppressionRuleApi),
        }
    )
}

export const getEnvironmentsErrorTrackingSuppressionRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const environmentsErrorTrackingSuppressionRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingSuppressionRuleApi: NonReadonly<PatchedErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<ErrorTrackingSuppressionRuleApi> => {
    return apiMutator<ErrorTrackingSuppressionRuleApi>(
        getEnvironmentsErrorTrackingSuppressionRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingSuppressionRuleApi),
        }
    )
}

export const getEnvironmentsErrorTrackingSuppressionRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const environmentsErrorTrackingSuppressionRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingSuppressionRulesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingSuppressionRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/reorder/`
}

export const environmentsErrorTrackingSuppressionRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingSuppressionRuleApi: NonReadonly<PatchedErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingSuppressionRulesReorderPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingSuppressionRuleApi),
    })
}

export const getEnvironmentsErrorTrackingSymbolSetsListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingSymbolSetsListParams
) => {
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

export const environmentsErrorTrackingSymbolSetsList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingSymbolSetsListParams,
    options?: RequestInit
): Promise<PaginatedErrorTrackingSymbolSetListApi> => {
    return apiMutator<PaginatedErrorTrackingSymbolSetListApi>(
        getEnvironmentsErrorTrackingSymbolSetsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsErrorTrackingSymbolSetsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/`
}

export const environmentsErrorTrackingSymbolSetsCreate = async (
    projectId: string,
    environmentsErrorTrackingSymbolSetsCreateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getEnvironmentsErrorTrackingSymbolSetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(environmentsErrorTrackingSymbolSetsCreateBody),
    })
}

export const getEnvironmentsErrorTrackingSymbolSetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const environmentsErrorTrackingSymbolSetsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getEnvironmentsErrorTrackingSymbolSetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsErrorTrackingSymbolSetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const environmentsErrorTrackingSymbolSetsUpdate = async (
    projectId: string,
    id: string,
    environmentsErrorTrackingSymbolSetsUpdateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(getEnvironmentsErrorTrackingSymbolSetsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        body: JSON.stringify(environmentsErrorTrackingSymbolSetsUpdateBody),
    })
}

export const getEnvironmentsErrorTrackingSymbolSetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const environmentsErrorTrackingSymbolSetsPartialUpdate = async (
    projectId: string,
    id: string,
    environmentsErrorTrackingSymbolSetsPartialUpdateBody: NonReadonly<PatchedErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<ErrorTrackingSymbolSetApi> => {
    return apiMutator<ErrorTrackingSymbolSetApi>(
        getEnvironmentsErrorTrackingSymbolSetsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            body: JSON.stringify(environmentsErrorTrackingSymbolSetsPartialUpdateBody),
        }
    )
}

export const getEnvironmentsErrorTrackingSymbolSetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const environmentsErrorTrackingSymbolSetsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingSymbolSetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsErrorTrackingSymbolSetsFinishUploadUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/finish_upload/`
}

export const environmentsErrorTrackingSymbolSetsFinishUploadUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingSymbolSetsFinishUploadUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getEnvironmentsErrorTrackingSymbolSetsBulkFinishUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/bulk_finish_upload/`
}

export const environmentsErrorTrackingSymbolSetsBulkFinishUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingSymbolSetsBulkFinishUploadCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getEnvironmentsErrorTrackingSymbolSetsBulkStartUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/bulk_start_upload/`
}

export const environmentsErrorTrackingSymbolSetsBulkStartUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingSymbolSetsBulkStartUploadCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingSymbolSetApi),
    })
}

export const getEnvironmentsErrorTrackingSymbolSetsStartUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/start_upload/`
}

export const environmentsErrorTrackingSymbolSetsStartUploadCreate = async (
    projectId: string,
    environmentsErrorTrackingSymbolSetsStartUploadCreateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsErrorTrackingSymbolSetsStartUploadCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(environmentsErrorTrackingSymbolSetsStartUploadCreateBody),
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
        ? `/api/projects/${projectId}/error_tracking/releases/?${stringifiedParams}`
        : `/api/projects/${projectId}/error_tracking/releases/`
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
    return `/api/projects/${projectId}/error_tracking/releases/`
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
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/releases/hash/${hashId}/`
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

export const getErrorTrackingSymbolSetsListUrl = (projectId: string, params?: ErrorTrackingSymbolSetsListParams) => {
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/finish_upload/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/bulk_finish_upload/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/bulk_start_upload/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/start_upload/`
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
