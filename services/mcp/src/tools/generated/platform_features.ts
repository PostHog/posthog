// AUTO-GENERATED from products/platform_features/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ActivityLogListQueryParams,
    AdvancedActivityLogsListQueryParams,
    ApprovalPoliciesListQueryParams,
    ApprovalPoliciesRetrieveParams,
    ChangeRequestsListQueryParams,
    ChangeRequestsRetrieveParams,
    CommentsListQueryParams,
    CommentsRetrieveParams,
    CommentsThreadRetrieveParams,
    MembersListQueryParams,
    RolesListQueryParams,
    RolesRetrieveParams,
    RolesRoleMembershipsListParams,
    RolesRoleMembershipsListQueryParams,
} from '@/generated/platform_features/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ChangeRequestsListSchema = ChangeRequestsListQueryParams

const changeRequestsList = (): ToolBase<typeof ChangeRequestsListSchema, Schemas.PaginatedChangeRequestList> => ({
    name: 'change-requests-list',
    schema: ChangeRequestsListSchema,
    handler: async (context: Context, params: z.infer<typeof ChangeRequestsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedChangeRequestList>({
            method: 'GET',
            path: `/api/environments/${projectId}/change_requests/`,
            query: {
                action_key: params.action_key,
                limit: params.limit,
                offset: params.offset,
                requester: params.requester,
                resource_id: params.resource_id,
                resource_type: params.resource_type,
                state: params.state,
            },
        })
        return result
    },
})

const ChangeRequestGetSchema = ChangeRequestsRetrieveParams.omit({ project_id: true })

const changeRequestGet = (): ToolBase<typeof ChangeRequestGetSchema, Schemas.ChangeRequest> => ({
    name: 'change-request-get',
    schema: ChangeRequestGetSchema,
    handler: async (context: Context, params: z.infer<typeof ChangeRequestGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ChangeRequest>({
            method: 'GET',
            path: `/api/environments/${projectId}/change_requests/${params.id}/`,
        })
        return result
    },
})

const ApprovalPoliciesListSchema = ApprovalPoliciesListQueryParams

const approvalPoliciesList = (): ToolBase<typeof ApprovalPoliciesListSchema, Schemas.PaginatedApprovalPolicyList> => ({
    name: 'approval-policies-list',
    schema: ApprovalPoliciesListSchema,
    handler: async (context: Context, params: z.infer<typeof ApprovalPoliciesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedApprovalPolicyList>({
            method: 'GET',
            path: `/api/environments/${projectId}/approval_policies/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const ApprovalPolicyGetSchema = ApprovalPoliciesRetrieveParams.omit({ project_id: true })

const approvalPolicyGet = (): ToolBase<typeof ApprovalPolicyGetSchema, Schemas.ApprovalPolicy> => ({
    name: 'approval-policy-get',
    schema: ApprovalPolicyGetSchema,
    handler: async (context: Context, params: z.infer<typeof ApprovalPolicyGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ApprovalPolicy>({
            method: 'GET',
            path: `/api/environments/${projectId}/approval_policies/${params.id}/`,
        })
        return result
    },
})

const CommentsListSchema = CommentsListQueryParams

const commentsList = (): ToolBase<typeof CommentsListSchema, Schemas.PaginatedCommentList> => ({
    name: 'comments-list',
    schema: CommentsListSchema,
    handler: async (context: Context, params: z.infer<typeof CommentsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCommentList>({
            method: 'GET',
            path: `/api/projects/${projectId}/comments/`,
            query: {
                cursor: params.cursor,
                item_id: params.item_id,
                scope: params.scope,
                search: params.search,
                source_comment: params.source_comment,
            },
        })
        return result
    },
})

const CommentGetSchema = CommentsRetrieveParams.omit({ project_id: true })

const commentGet = (): ToolBase<typeof CommentGetSchema, Schemas.Comment> => ({
    name: 'comment-get',
    schema: CommentGetSchema,
    handler: async (context: Context, params: z.infer<typeof CommentGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Comment>({
            method: 'GET',
            path: `/api/projects/${projectId}/comments/${params.id}/`,
        })
        return result
    },
})

const CommentThreadSchema = CommentsThreadRetrieveParams.omit({ project_id: true })

const commentThread = (): ToolBase<typeof CommentThreadSchema, unknown> => ({
    name: 'comment-thread',
    schema: CommentThreadSchema,
    handler: async (context: Context, params: z.infer<typeof CommentThreadSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/comments/${params.id}/thread/`,
        })
        return result
    },
})

const CommentCountSchema = z.object({})

const commentCount = (): ToolBase<typeof CommentCountSchema, unknown> => ({
    name: 'comment-count',
    schema: CommentCountSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof CommentCountSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/comments/count/`,
        })
        return result
    },
})

const ActivityLogListSchema = ActivityLogListQueryParams.extend({
    page_size: ActivityLogListQueryParams.shape['page_size'].default(10).optional(),
})

const activityLogList = (): ToolBase<
    typeof ActivityLogListSchema,
    WithPostHogUrl<Schemas.PaginatedActivityLogList>
> => ({
    name: 'activity-log-list',
    schema: ActivityLogListSchema,
    handler: async (context: Context, params: z.infer<typeof ActivityLogListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedActivityLogList>({
            method: 'GET',
            path: `/api/projects/${projectId}/activity_log/`,
            query: {
                item_id: params.item_id,
                page: params.page,
                page_size: params.page_size,
                scope: params.scope,
                scopes: params.scopes,
                user: params.user,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'user.id',
                    'user.first_name',
                    'user.last_name',
                    'user.email',
                    'activity',
                    'scope',
                    'item_id',
                    'detail.name',
                    'detail.short_id',
                    'detail.type',
                    'created_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/activity')
    },
})

const AdvancedActivityLogsListSchema = AdvancedActivityLogsListQueryParams.extend({
    page_size: AdvancedActivityLogsListQueryParams.shape['page_size'].default(10).optional(),
})

const advancedActivityLogsList = (): ToolBase<
    typeof AdvancedActivityLogsListSchema,
    WithPostHogUrl<Schemas.PaginatedActivityLogList>
> => ({
    name: 'advanced-activity-logs-list',
    schema: AdvancedActivityLogsListSchema,
    handler: async (context: Context, params: z.infer<typeof AdvancedActivityLogsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedActivityLogList>({
            method: 'GET',
            path: `/api/projects/${projectId}/advanced_activity_logs/`,
            query: {
                activities: params.activities,
                detail_filters: params.detail_filters,
                end_date: params.end_date,
                hogql_filter: params.hogql_filter,
                is_system: params.is_system,
                item_ids: params.item_ids,
                page: params.page,
                page_size: params.page_size,
                scopes: params.scopes,
                search_text: params.search_text,
                start_date: params.start_date,
                users: params.users,
                was_impersonated: params.was_impersonated,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'user.id',
                    'user.first_name',
                    'user.last_name',
                    'user.email',
                    'activity',
                    'scope',
                    'item_id',
                    'detail.name',
                    'detail.short_id',
                    'detail.type',
                    'detail.changes',
                    'created_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/activity')
    },
})

const AdvancedActivityLogsFiltersSchema = z.object({})

const advancedActivityLogsFilters = (): ToolBase<
    typeof AdvancedActivityLogsFiltersSchema,
    Schemas.AvailableFiltersResponse
> => ({
    name: 'advanced-activity-logs-filters',
    schema: AdvancedActivityLogsFiltersSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof AdvancedActivityLogsFiltersSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AvailableFiltersResponse>({
            method: 'GET',
            path: `/api/projects/${projectId}/advanced_activity_logs/available_filters/`,
        })
        return result
    },
})

const OrgMembersListSchema = MembersListQueryParams

const orgMembersList = (): ToolBase<typeof OrgMembersListSchema, Schemas.PaginatedOrganizationMemberList> => ({
    name: 'org-members-list',
    schema: OrgMembersListSchema,
    handler: async (context: Context, params: z.infer<typeof OrgMembersListSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.PaginatedOrganizationMemberList>({
            method: 'GET',
            path: `/api/organizations/${orgId}/members/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const RolesListSchema = RolesListQueryParams

const rolesList = (): ToolBase<typeof RolesListSchema, Schemas.PaginatedRoleList> => ({
    name: 'roles-list',
    schema: RolesListSchema,
    handler: async (context: Context, params: z.infer<typeof RolesListSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.PaginatedRoleList>({
            method: 'GET',
            path: `/api/organizations/${orgId}/roles/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const RoleGetSchema = RolesRetrieveParams.omit({ organization_id: true })

const roleGet = (): ToolBase<typeof RoleGetSchema, Schemas.Role> => ({
    name: 'role-get',
    schema: RoleGetSchema,
    handler: async (context: Context, params: z.infer<typeof RoleGetSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.Role>({
            method: 'GET',
            path: `/api/organizations/${orgId}/roles/${params.id}/`,
        })
        return result
    },
})

const RoleMembersListSchema = RolesRoleMembershipsListParams.omit({ organization_id: true }).extend(
    RolesRoleMembershipsListQueryParams.shape
)

const roleMembersList = (): ToolBase<typeof RoleMembersListSchema, Schemas.PaginatedRoleMembershipList> => ({
    name: 'role-members-list',
    schema: RoleMembersListSchema,
    handler: async (context: Context, params: z.infer<typeof RoleMembersListSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.PaginatedRoleMembershipList>({
            method: 'GET',
            path: `/api/organizations/${orgId}/roles/${params.role_id}/role_memberships/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'change-requests-list': changeRequestsList,
    'change-request-get': changeRequestGet,
    'approval-policies-list': approvalPoliciesList,
    'approval-policy-get': approvalPolicyGet,
    'comments-list': commentsList,
    'comment-get': commentGet,
    'comment-thread': commentThread,
    'comment-count': commentCount,
    'activity-log-list': activityLogList,
    'advanced-activity-logs-list': advancedActivityLogsList,
    'advanced-activity-logs-filters': advancedActivityLogsFilters,
    'org-members-list': orgMembersList,
    'roles-list': rolesList,
    'role-get': roleGet,
    'role-members-list': roleMembersList,
}
