/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    ActivityLogApi,
    ApprovalPolicyApi,
    ChangeRequestApi,
    ChangeRequestApproveApi,
    ChangeRequestRejectApi,
    CommentApi,
    OrganizationApi,
    OrganizationMemberApi,
    PatchedApprovalPolicyApi,
    PatchedCommentApi,
    PatchedOrganizationApi,
    PatchedOrganizationMemberApi,
    PatchedPinnedSceneTabsApi,
    PatchedRoleApi,
    RoleApi,
    RoleMembershipApi,
} from './api.zod.schemas'

export const CreateBody = OrganizationApi

export const UpdateBody = OrganizationApi

export const PartialUpdateBody = PatchedOrganizationApi

export const MembersUpdateBody = OrganizationMemberApi

export const MembersPartialUpdateBody = PatchedOrganizationMemberApi

/**
 * Role endpoints disclose member records, so they scope them the same way the members list
 * does when the org restricts member list visibility.
 */
export const RolesCreateBody = RoleApi

/**
 * Role endpoints disclose member records, so they scope them the same way the members list
 * does when the org restricts member list visibility.
 */
export const RolesUpdateBody = RoleApi

/**
 * Role endpoints disclose member records, so they scope them the same way the members list
 * does when the org restricts member list visibility.
 */
export const RolesPartialUpdateBody = PatchedRoleApi

/**
 * Role endpoints disclose member records, so they scope them the same way the members list
 * does when the org restricts member list visibility.
 */
export const RolesRoleMembershipsCreateBody = RoleMembershipApi

export const AdvancedActivityLogsExportCreateBody = ActivityLogApi

export const ApprovalPoliciesCreateBody = ApprovalPolicyApi

export const ApprovalPoliciesUpdateBody = ApprovalPolicyApi

export const ApprovalPoliciesPartialUpdateBody = PatchedApprovalPolicyApi

/**
 * Approve a change request.
 * If quorum is reached, automatically applies the change immediately.
 */
export const ChangeRequestsApproveCreateBody = ChangeRequestApproveApi

/**
 * Cancel a change request.
 * Only the requester can cancel their own pending change request.
 */
export const ChangeRequestsCancelCreateBody = ChangeRequestApi

/**
 * Reject a change request.
 */
export const ChangeRequestsRejectCreateBody = ChangeRequestRejectApi

export const CommentsCreateBody = CommentApi

export const CommentsUpdateBody = CommentApi

export const CommentsPartialUpdateBody = PatchedCommentApi

/**
 * Update the authenticated user's pinned sidebar tabs and/or homepage for the current team. Pass `@me` as the UUID. Send `tabs` to replace the pinned tab list, `homepage` to set the home destination (any PostHog URL — dashboard, insight, search results, scene). Either field may be omitted to leave it unchanged; sending `homepage: null` or `{}` clears the homepage.
 */
export const UserHomeSettingsPartialUpdateBody = PatchedPinnedSceneTabsApi
