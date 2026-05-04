/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const approvalPoliciesCreateBodyActionKeyMax = 128

export const ApprovalPoliciesCreateBody = /* @__PURE__ */ zod.object({
    action_key: zod.string().max(approvalPoliciesCreateBodyActionKeyMax),
    conditions: zod.unknown().optional(),
    approver_config: zod.unknown(),
    allow_self_approve: zod.boolean().optional(),
    bypass_org_membership_levels: zod.unknown().optional(),
    bypass_roles: zod.array(zod.uuid()).optional(),
    expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
    enabled: zod.boolean().optional(),
})

export const approvalPoliciesUpdateBodyActionKeyMax = 128

export const ApprovalPoliciesUpdateBody = /* @__PURE__ */ zod.object({
    action_key: zod.string().max(approvalPoliciesUpdateBodyActionKeyMax),
    conditions: zod.unknown().optional(),
    approver_config: zod.unknown(),
    allow_self_approve: zod.boolean().optional(),
    bypass_org_membership_levels: zod.unknown().optional(),
    bypass_roles: zod.array(zod.uuid()).optional(),
    expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
    enabled: zod.boolean().optional(),
})

export const approvalPoliciesPartialUpdateBodyActionKeyMax = 128

export const ApprovalPoliciesPartialUpdateBody = /* @__PURE__ */ zod.object({
    action_key: zod.string().max(approvalPoliciesPartialUpdateBodyActionKeyMax).optional(),
    conditions: zod.unknown().optional(),
    approver_config: zod.unknown().optional(),
    allow_self_approve: zod.boolean().optional(),
    bypass_org_membership_levels: zod.unknown().optional(),
    bypass_roles: zod.array(zod.uuid()).optional(),
    expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
    enabled: zod.boolean().optional(),
})

/**
 * Approve a change request.
If quorum is reached, automatically applies the change immediately.
 */
export const ChangeRequestsApproveCreateBody = /* @__PURE__ */ zod.object({})

/**
 * Cancel a change request.
Only the requester can cancel their own pending change request.
 */
export const ChangeRequestsCancelCreateBody = /* @__PURE__ */ zod.object({})

/**
 * Reject a change request.
 */
export const ChangeRequestsRejectCreateBody = /* @__PURE__ */ zod.object({})

export const createBodyNameMax = 64

export const CreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(createBodyNameMax),
    logo_media_id: zod.uuid().nullish(),
    enforce_2fa: zod.boolean().nullish(),
    members_can_invite: zod.boolean().nullish(),
    members_can_use_personal_api_keys: zod.boolean().optional(),
    allow_publicly_shared_resources: zod.boolean().optional(),
    is_ai_data_processing_approved: zod.boolean().nullish(),
    default_experiment_stats_method: zod
        .union([
            zod.enum(['bayesian', 'frequentist']).describe('* `bayesian` - Bayesian\n* `frequentist` - Frequentist'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Default statistical method for new experiments in this organization.\n\n* `bayesian` - Bayesian\n* `frequentist` - Frequentist'
        ),
    default_anonymize_ips: zod
        .boolean()
        .optional()
        .describe("Default setting for 'Discard client IP data' for new projects in this organization."),
    default_role_id: zod
        .string()
        .nullish()
        .describe('ID of the role to automatically assign to new members joining the organization'),
})

export const updateBodyNameMax = 64

export const UpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(updateBodyNameMax),
    logo_media_id: zod.uuid().nullish(),
    enforce_2fa: zod.boolean().nullish(),
    members_can_invite: zod.boolean().nullish(),
    members_can_use_personal_api_keys: zod.boolean().optional(),
    allow_publicly_shared_resources: zod.boolean().optional(),
    is_ai_data_processing_approved: zod.boolean().nullish(),
    default_experiment_stats_method: zod
        .union([
            zod.enum(['bayesian', 'frequentist']).describe('* `bayesian` - Bayesian\n* `frequentist` - Frequentist'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Default statistical method for new experiments in this organization.\n\n* `bayesian` - Bayesian\n* `frequentist` - Frequentist'
        ),
    default_anonymize_ips: zod
        .boolean()
        .optional()
        .describe("Default setting for 'Discard client IP data' for new projects in this organization."),
    default_role_id: zod
        .string()
        .nullish()
        .describe('ID of the role to automatically assign to new members joining the organization'),
})

export const partialUpdateBodyNameMax = 64

export const PartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(partialUpdateBodyNameMax).optional(),
    logo_media_id: zod.uuid().nullish(),
    enforce_2fa: zod.boolean().nullish(),
    members_can_invite: zod.boolean().nullish(),
    members_can_use_personal_api_keys: zod.boolean().optional(),
    allow_publicly_shared_resources: zod.boolean().optional(),
    is_ai_data_processing_approved: zod.boolean().nullish(),
    default_experiment_stats_method: zod
        .union([
            zod.enum(['bayesian', 'frequentist']).describe('* `bayesian` - Bayesian\n* `frequentist` - Frequentist'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Default statistical method for new experiments in this organization.\n\n* `bayesian` - Bayesian\n* `frequentist` - Frequentist'
        ),
    default_anonymize_ips: zod
        .boolean()
        .optional()
        .describe("Default setting for 'Discard client IP data' for new projects in this organization."),
    default_role_id: zod
        .string()
        .nullish()
        .describe('ID of the role to automatically assign to new members joining the organization'),
})

export const MembersUpdateBody = /* @__PURE__ */ zod.object({
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .optional()
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner'),
})

export const MembersPartialUpdateBody = /* @__PURE__ */ zod.object({
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .optional()
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner'),
})

export const rolesCreateBodyNameMax = 200

export const RolesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(rolesCreateBodyNameMax),
})

export const rolesUpdateBodyNameMax = 200

export const RolesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(rolesUpdateBodyNameMax),
})

export const rolesPartialUpdateBodyNameMax = 200

export const RolesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(rolesPartialUpdateBodyNameMax).optional(),
})

export const RolesRoleMembershipsCreateBody = /* @__PURE__ */ zod.object({
    user_uuid: zod.uuid(),
})

export const advancedActivityLogsExportCreateBodyUserDistinctIdMax = 200

export const advancedActivityLogsExportCreateBodyUserFirstNameMax = 150

export const advancedActivityLogsExportCreateBodyUserLastNameMax = 150

export const advancedActivityLogsExportCreateBodyUserEmailMax = 254

export const advancedActivityLogsExportCreateBodyClientMax = 32

export const advancedActivityLogsExportCreateBodyActivityMax = 79

export const advancedActivityLogsExportCreateBodyItemIdMax = 72

export const advancedActivityLogsExportCreateBodyScopeMax = 79

export const AdvancedActivityLogsExportCreateBody = /* @__PURE__ */ zod.object({
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(advancedActivityLogsExportCreateBodyUserDistinctIdMax).nullish(),
        first_name: zod.string().max(advancedActivityLogsExportCreateBodyUserFirstNameMax).optional(),
        last_name: zod.string().max(advancedActivityLogsExportCreateBodyUserLastNameMax).optional(),
        email: zod.email().max(advancedActivityLogsExportCreateBodyUserEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    organization_id: zod.uuid().nullish(),
    was_impersonated: zod.boolean().nullish(),
    is_system: zod.boolean().nullish(),
    client: zod.string().max(advancedActivityLogsExportCreateBodyClientMax).nullish(),
    activity: zod.string().max(advancedActivityLogsExportCreateBodyActivityMax),
    item_id: zod.string().max(advancedActivityLogsExportCreateBodyItemIdMax).nullish(),
    scope: zod.string().max(advancedActivityLogsExportCreateBodyScopeMax),
    detail: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}).optional(),
})

export const commentsCreateBodyItemIdMax = 72

export const commentsCreateBodyScopeMax = 79

export const CommentsCreateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    mentions: zod.array(zod.number()).optional(),
    slug: zod.string().optional(),
    content: zod.string().nullish(),
    rich_content: zod.unknown().nullish(),
    item_id: zod.string().max(commentsCreateBodyItemIdMax).nullish(),
    item_context: zod.unknown().nullish(),
    scope: zod.string().max(commentsCreateBodyScopeMax),
    source_comment: zod.uuid().nullish(),
})

export const commentsUpdateBodyItemIdMax = 72

export const commentsUpdateBodyScopeMax = 79

export const CommentsUpdateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    mentions: zod.array(zod.number()).optional(),
    slug: zod.string().optional(),
    content: zod.string().nullish(),
    rich_content: zod.unknown().nullish(),
    item_id: zod.string().max(commentsUpdateBodyItemIdMax).nullish(),
    item_context: zod.unknown().nullish(),
    scope: zod.string().max(commentsUpdateBodyScopeMax),
    source_comment: zod.uuid().nullish(),
})

export const commentsPartialUpdateBodyItemIdMax = 72

export const commentsPartialUpdateBodyScopeMax = 79

export const CommentsPartialUpdateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    mentions: zod.array(zod.number()).optional(),
    slug: zod.string().optional(),
    content: zod.string().nullish(),
    rich_content: zod.unknown().nullish(),
    item_id: zod.string().max(commentsPartialUpdateBodyItemIdMax).nullish(),
    item_context: zod.unknown().nullish(),
    scope: zod.string().max(commentsPartialUpdateBodyScopeMax).optional(),
    source_comment: zod.uuid().nullish(),
})

/**
 * Update the authenticated user's pinned sidebar tabs and/or homepage for the current team. Pass `@me` as the UUID. Send `tabs` to replace the pinned tab list, `homepage` to set the home destination (any PostHog URL — dashboard, insight, search results, scene). Either field may be omitted to leave it unchanged; sending `homepage: null` or `{}` clears the homepage.
 */
export const UserHomeSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    tabs: zod
        .array(
            zod.object({
                id: zod
                    .string()
                    .optional()
                    .describe('Stable identifier for the tab. Generated client-side; safe to omit on create.'),
                pathname: zod
                    .string()
                    .optional()
                    .describe(
                        'URL pathname the tab points at — for example `/project/123/dashboard/45` or `/project/123/insights`. Combined with `search` and `hash` to reconstruct the destination.'
                    ),
                search: zod
                    .string()
                    .optional()
                    .describe(
                        'Query string portion of the URL, including the leading `?`. Empty string when there is no query.'
                    ),
                hash: zod
                    .string()
                    .optional()
                    .describe(
                        'Fragment portion of the URL, including the leading `#`. Empty string when there is no fragment.'
                    ),
                title: zod
                    .string()
                    .optional()
                    .describe(
                        'Default tab title derived from the destination scene. Used when `customTitle` is not set.'
                    ),
                customTitle: zod
                    .string()
                    .nullish()
                    .describe('Optional user-provided title that overrides `title` in the navigation UI.'),
                iconType: zod
                    .string()
                    .optional()
                    .describe(
                        'Icon key shown next to the tab in the sidebar — for example `dashboard`, `insight`, `blank`.'
                    ),
                sceneId: zod
                    .string()
                    .nullish()
                    .describe(
                        'Scene identifier resolved from the pathname when known — used by the frontend for icon/title hints.'
                    ),
                sceneKey: zod
                    .string()
                    .nullish()
                    .describe(
                        'Scene key (logic key) for the destination, paired with `sceneParams` for deeper routing context.'
                    ),
                sceneParams: zod
                    .unknown()
                    .optional()
                    .describe(
                        'Free-form scene parameters captured at pin time, used by the frontend to rehydrate the destination.'
                    ),
                pinned: zod
                    .boolean()
                    .optional()
                    .describe('Whether this entry is pinned. Always coerced to true on save — pass true or omit.'),
            })
        )
        .optional()
        .describe(
            'Ordered list of pinned navigation tabs shown in the sidebar for the authenticated user within the current team. Send the full list to replace the existing pins; omit to leave them unchanged.'
        ),
    homepage: zod
        .object({
            id: zod
                .string()
                .optional()
                .describe('Stable identifier for the tab. Generated client-side; safe to omit on create.'),
            pathname: zod
                .string()
                .optional()
                .describe(
                    'URL pathname the tab points at — for example `/project/123/dashboard/45` or `/project/123/insights`. Combined with `search` and `hash` to reconstruct the destination.'
                ),
            search: zod
                .string()
                .optional()
                .describe(
                    'Query string portion of the URL, including the leading `?`. Empty string when there is no query.'
                ),
            hash: zod
                .string()
                .optional()
                .describe(
                    'Fragment portion of the URL, including the leading `#`. Empty string when there is no fragment.'
                ),
            title: zod
                .string()
                .optional()
                .describe('Default tab title derived from the destination scene. Used when `customTitle` is not set.'),
            customTitle: zod
                .string()
                .nullish()
                .describe('Optional user-provided title that overrides `title` in the navigation UI.'),
            iconType: zod
                .string()
                .optional()
                .describe(
                    'Icon key shown next to the tab in the sidebar — for example `dashboard`, `insight`, `blank`.'
                ),
            sceneId: zod
                .string()
                .nullish()
                .describe(
                    'Scene identifier resolved from the pathname when known — used by the frontend for icon/title hints.'
                ),
            sceneKey: zod
                .string()
                .nullish()
                .describe(
                    'Scene key (logic key) for the destination, paired with `sceneParams` for deeper routing context.'
                ),
            sceneParams: zod
                .unknown()
                .optional()
                .describe(
                    'Free-form scene parameters captured at pin time, used by the frontend to rehydrate the destination.'
                ),
            pinned: zod
                .boolean()
                .optional()
                .describe('Whether this entry is pinned. Always coerced to true on save — pass true or omit.'),
        })
        .nullish()
        .describe(
            "Tab descriptor for the user's chosen home page — the destination opened when they click the PostHog logo or hit `/`. Set to a tab descriptor to pick a homepage, send `null` or `{}` to clear it and fall back to the project default."
        ),
})
