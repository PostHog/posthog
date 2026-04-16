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
    ActivityLogApi,
    ActivityLogListParams,
    AdvancedActivityLogsListParams,
    ApprovalPoliciesListParams,
    ApprovalPolicyApi,
    AvailableFiltersResponseApi,
    ChangeRequestApi,
    ChangeRequestsListParams,
    CommentApi,
    CommentsListParams,
    ListParams,
    MembersListParams,
    OrganizationApi,
    OrganizationMemberApi,
    PaginatedActivityLogListApi,
    PaginatedApprovalPolicyListApi,
    PaginatedChangeRequestListApi,
    PaginatedCommentListApi,
    PaginatedOrganizationListApi,
    PaginatedOrganizationMemberListApi,
    PatchedApprovalPolicyApi,
    PatchedCommentApi,
    PatchedOrganizationApi,
    PatchedOrganizationMemberApi,
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

export const getApprovalPoliciesListUrl = (projectId: string, params?: ApprovalPoliciesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/approval_policies/?${stringifiedParams}`
        : `/api/environments/${projectId}/approval_policies/`
}

export const approvalPoliciesList = async (
    projectId: string,
    params?: ApprovalPoliciesListParams,
    options?: RequestInit
): Promise<PaginatedApprovalPolicyListApi> => {
    return apiMutator<PaginatedApprovalPolicyListApi>(getApprovalPoliciesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getApprovalPoliciesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/approval_policies/`
}

export const approvalPoliciesCreate = async (
    projectId: string,
    approvalPolicyApi: NonReadonly<ApprovalPolicyApi>,
    options?: RequestInit
): Promise<ApprovalPolicyApi> => {
    return apiMutator<ApprovalPolicyApi>(getApprovalPoliciesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(approvalPolicyApi),
    })
}

export const getApprovalPoliciesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/approval_policies/${id}/`
}

export const approvalPoliciesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ApprovalPolicyApi> => {
    return apiMutator<ApprovalPolicyApi>(getApprovalPoliciesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getApprovalPoliciesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/approval_policies/${id}/`
}

export const approvalPoliciesUpdate = async (
    projectId: string,
    id: string,
    approvalPolicyApi: NonReadonly<ApprovalPolicyApi>,
    options?: RequestInit
): Promise<ApprovalPolicyApi> => {
    return apiMutator<ApprovalPolicyApi>(getApprovalPoliciesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(approvalPolicyApi),
    })
}

export const getApprovalPoliciesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/approval_policies/${id}/`
}

export const approvalPoliciesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedApprovalPolicyApi: NonReadonly<PatchedApprovalPolicyApi>,
    options?: RequestInit
): Promise<ApprovalPolicyApi> => {
    return apiMutator<ApprovalPolicyApi>(getApprovalPoliciesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedApprovalPolicyApi),
    })
}

export const getApprovalPoliciesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/approval_policies/${id}/`
}

export const approvalPoliciesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getApprovalPoliciesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getChangeRequestsListUrl = (projectId: string, params?: ChangeRequestsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/change_requests/?${stringifiedParams}`
        : `/api/environments/${projectId}/change_requests/`
}

export const changeRequestsList = async (
    projectId: string,
    params?: ChangeRequestsListParams,
    options?: RequestInit
): Promise<PaginatedChangeRequestListApi> => {
    return apiMutator<PaginatedChangeRequestListApi>(getChangeRequestsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getChangeRequestsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/change_requests/${id}/`
}

export const changeRequestsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ChangeRequestApi> => {
    return apiMutator<ChangeRequestApi>(getChangeRequestsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Approve a change request.
If quorum is reached, automatically applies the change immediately.
 */
export const getChangeRequestsApproveCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/change_requests/${id}/approve/`
}

export const changeRequestsApproveCreate = async (
    projectId: string,
    id: string,
    changeRequestApi: NonReadonly<ChangeRequestApi>,
    options?: RequestInit
): Promise<ChangeRequestApi> => {
    return apiMutator<ChangeRequestApi>(getChangeRequestsApproveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(changeRequestApi),
    })
}

/**
 * Cancel a change request.
Only the requester can cancel their own pending change request.
 */
export const getChangeRequestsCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/change_requests/${id}/cancel/`
}

export const changeRequestsCancelCreate = async (
    projectId: string,
    id: string,
    changeRequestApi: NonReadonly<ChangeRequestApi>,
    options?: RequestInit
): Promise<ChangeRequestApi> => {
    return apiMutator<ChangeRequestApi>(getChangeRequestsCancelCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(changeRequestApi),
    })
}

/**
 * Reject a change request.
 */
export const getChangeRequestsRejectCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/change_requests/${id}/reject/`
}

export const changeRequestsRejectCreate = async (
    projectId: string,
    id: string,
    changeRequestApi: NonReadonly<ChangeRequestApi>,
    options?: RequestInit
): Promise<ChangeRequestApi> => {
    return apiMutator<ChangeRequestApi>(getChangeRequestsRejectCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(changeRequestApi),
    })
}

export const getListUrl = (params?: ListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0 ? `/api/organizations/?${stringifiedParams}` : `/api/organizations/`
}

export const list = async (params?: ListParams, options?: RequestInit): Promise<PaginatedOrganizationListApi> => {
    return apiMutator<PaginatedOrganizationListApi>(getListUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getCreateUrl = () => {
    return `/api/organizations/`
}

export const create = async (
    organizationApi: NonReadonly<OrganizationApi>,
    options?: RequestInit
): Promise<OrganizationApi> => {
    return apiMutator<OrganizationApi>(getCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationApi),
    })
}

export const getRetrieveUrl = (id: string) => {
    return `/api/organizations/${id}/`
}

export const retrieve = async (id: string, options?: RequestInit): Promise<OrganizationApi> => {
    return apiMutator<OrganizationApi>(getRetrieveUrl(id), {
        ...options,
        method: 'GET',
    })
}

export const getUpdateUrl = (id: string) => {
    return `/api/organizations/${id}/`
}

export const update = async (
    id: string,
    organizationApi: NonReadonly<OrganizationApi>,
    options?: RequestInit
): Promise<OrganizationApi> => {
    return apiMutator<OrganizationApi>(getUpdateUrl(id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationApi),
    })
}

export const getPartialUpdateUrl = (id: string) => {
    return `/api/organizations/${id}/`
}

export const partialUpdate = async (
    id: string,
    patchedOrganizationApi: NonReadonly<PatchedOrganizationApi>,
    options?: RequestInit
): Promise<OrganizationApi> => {
    return apiMutator<OrganizationApi>(getPartialUpdateUrl(id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedOrganizationApi),
    })
}

export const getDestroyUrl = (id: string) => {
    return `/api/organizations/${id}/`
}

export const destroy = async (id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDestroyUrl(id), {
        ...options,
        method: 'DELETE',
    })
}

export const getMembersListUrl = (organizationId: string, params?: MembersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/members/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/members/`
}

export const membersList = async (
    organizationId: string,
    params?: MembersListParams,
    options?: RequestInit
): Promise<PaginatedOrganizationMemberListApi> => {
    return apiMutator<PaginatedOrganizationMemberListApi>(getMembersListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMembersUpdateUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersUpdate = async (
    organizationId: string,
    userUuid: string,
    organizationMemberApi: NonReadonly<OrganizationMemberApi>,
    options?: RequestInit
): Promise<OrganizationMemberApi> => {
    return apiMutator<OrganizationMemberApi>(getMembersUpdateUrl(organizationId, userUuid), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationMemberApi),
    })
}

export const getMembersPartialUpdateUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersPartialUpdate = async (
    organizationId: string,
    userUuid: string,
    patchedOrganizationMemberApi: NonReadonly<PatchedOrganizationMemberApi>,
    options?: RequestInit
): Promise<OrganizationMemberApi> => {
    return apiMutator<OrganizationMemberApi>(getMembersPartialUpdateUrl(organizationId, userUuid), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedOrganizationMemberApi),
    })
}

export const getMembersDestroyUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersDestroy = async (
    organizationId: string,
    userUuid: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMembersDestroyUrl(organizationId, userUuid), {
        ...options,
        method: 'DELETE',
    })
}

export const getMembersScopedApiKeysRetrieveUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/scoped_api_keys/`
}

export const membersScopedApiKeysRetrieve = async (
    organizationId: string,
    userUuid: string,
    options?: RequestInit
): Promise<OrganizationMemberApi> => {
    return apiMutator<OrganizationMemberApi>(getMembersScopedApiKeysRetrieveUrl(organizationId, userUuid), {
        ...options,
        method: 'GET',
    })
}

export const getActivityLogListUrl = (projectId: string, params?: ActivityLogListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/activity_log/?${stringifiedParams}`
        : `/api/projects/${projectId}/activity_log/`
}

export const activityLogList = async (
    projectId: string,
    params?: ActivityLogListParams,
    options?: RequestInit
): Promise<PaginatedActivityLogListApi> => {
    return apiMutator<PaginatedActivityLogListApi>(getActivityLogListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAdvancedActivityLogsListUrl = (projectId: string, params?: AdvancedActivityLogsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/advanced_activity_logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/advanced_activity_logs/`
}

export const advancedActivityLogsList = async (
    projectId: string,
    params?: AdvancedActivityLogsListParams,
    options?: RequestInit
): Promise<PaginatedActivityLogListApi> => {
    return apiMutator<PaginatedActivityLogListApi>(getAdvancedActivityLogsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAdvancedActivityLogsAvailableFiltersRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/advanced_activity_logs/available_filters/`
}

export const advancedActivityLogsAvailableFiltersRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AvailableFiltersResponseApi> => {
    return apiMutator<AvailableFiltersResponseApi>(getAdvancedActivityLogsAvailableFiltersRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getAdvancedActivityLogsExportCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/advanced_activity_logs/export/`
}

export const advancedActivityLogsExportCreate = async (
    projectId: string,
    activityLogApi: NonReadonly<ActivityLogApi>,
    options?: RequestInit
): Promise<ActivityLogApi> => {
    return apiMutator<ActivityLogApi>(getAdvancedActivityLogsExportCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(activityLogApi),
    })
}

export const getCommentsListUrl = (projectId: string, params?: CommentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/comments/?${stringifiedParams}`
        : `/api/projects/${projectId}/comments/`
}

export const commentsList = async (
    projectId: string,
    params?: CommentsListParams,
    options?: RequestInit
): Promise<PaginatedCommentListApi> => {
    return apiMutator<PaginatedCommentListApi>(getCommentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCommentsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/comments/`
}

export const commentsCreate = async (
    projectId: string,
    commentApi: NonReadonly<CommentApi>,
    options?: RequestInit
): Promise<CommentApi> => {
    return apiMutator<CommentApi>(getCommentsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(commentApi),
    })
}

export const getCommentsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<CommentApi> => {
    return apiMutator<CommentApi>(getCommentsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCommentsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsUpdate = async (
    projectId: string,
    id: string,
    commentApi: NonReadonly<CommentApi>,
    options?: RequestInit
): Promise<CommentApi> => {
    return apiMutator<CommentApi>(getCommentsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(commentApi),
    })
}

export const getCommentsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCommentApi: NonReadonly<PatchedCommentApi>,
    options?: RequestInit
): Promise<CommentApi> => {
    return apiMutator<CommentApi>(getCommentsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCommentApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getCommentsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getCommentsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCommentsThreadRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/thread/`
}

export const commentsThreadRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCommentsThreadRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCommentsCountRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/comments/count/`
}

export const commentsCountRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCommentsCountRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
