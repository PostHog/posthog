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

export const approvalPoliciesListResponseResultsItemActionKeyMax = 128

export const approvalPoliciesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const approvalPoliciesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const approvalPoliciesListResponseResultsItemCreatedByOneLastNameMax = 150

export const approvalPoliciesListResponseResultsItemCreatedByOneEmailMax = 254

export const ApprovalPoliciesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            action_key: zod.string().max(approvalPoliciesListResponseResultsItemActionKeyMax),
            conditions: zod.unknown().optional(),
            approver_config: zod.unknown(),
            allow_self_approve: zod.boolean().optional(),
            bypass_org_membership_levels: zod.unknown().optional(),
            bypass_roles: zod.array(zod.uuid()).optional(),
            expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
            enabled: zod.boolean().optional(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(approvalPoliciesListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(approvalPoliciesListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod.string().max(approvalPoliciesListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(approvalPoliciesListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

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

export const approvalPoliciesRetrieveResponseActionKeyMax = 128

export const approvalPoliciesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const approvalPoliciesRetrieveResponseCreatedByOneFirstNameMax = 150

export const approvalPoliciesRetrieveResponseCreatedByOneLastNameMax = 150

export const approvalPoliciesRetrieveResponseCreatedByOneEmailMax = 254

export const ApprovalPoliciesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    action_key: zod.string().max(approvalPoliciesRetrieveResponseActionKeyMax),
    conditions: zod.unknown().optional(),
    approver_config: zod.unknown(),
    allow_self_approve: zod.boolean().optional(),
    bypass_org_membership_levels: zod.unknown().optional(),
    bypass_roles: zod.array(zod.uuid()).optional(),
    expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
    enabled: zod.boolean().optional(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(approvalPoliciesRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(approvalPoliciesRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(approvalPoliciesRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(approvalPoliciesRetrieveResponseCreatedByOneEmailMax),
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
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
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

export const approvalPoliciesUpdateResponseActionKeyMax = 128

export const approvalPoliciesUpdateResponseCreatedByOneDistinctIdMax = 200

export const approvalPoliciesUpdateResponseCreatedByOneFirstNameMax = 150

export const approvalPoliciesUpdateResponseCreatedByOneLastNameMax = 150

export const approvalPoliciesUpdateResponseCreatedByOneEmailMax = 254

export const ApprovalPoliciesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    action_key: zod.string().max(approvalPoliciesUpdateResponseActionKeyMax),
    conditions: zod.unknown().optional(),
    approver_config: zod.unknown(),
    allow_self_approve: zod.boolean().optional(),
    bypass_org_membership_levels: zod.unknown().optional(),
    bypass_roles: zod.array(zod.uuid()).optional(),
    expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
    enabled: zod.boolean().optional(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(approvalPoliciesUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(approvalPoliciesUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(approvalPoliciesUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(approvalPoliciesUpdateResponseCreatedByOneEmailMax),
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
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
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

export const approvalPoliciesPartialUpdateResponseActionKeyMax = 128

export const approvalPoliciesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const approvalPoliciesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const approvalPoliciesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const approvalPoliciesPartialUpdateResponseCreatedByOneEmailMax = 254

export const ApprovalPoliciesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    action_key: zod.string().max(approvalPoliciesPartialUpdateResponseActionKeyMax),
    conditions: zod.unknown().optional(),
    approver_config: zod.unknown(),
    allow_self_approve: zod.boolean().optional(),
    bypass_org_membership_levels: zod.unknown().optional(),
    bypass_roles: zod.array(zod.uuid()).optional(),
    expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
    enabled: zod.boolean().optional(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(approvalPoliciesPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(approvalPoliciesPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(approvalPoliciesPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(approvalPoliciesPartialUpdateResponseCreatedByOneEmailMax),
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
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const changeRequestsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const changeRequestsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const changeRequestsListResponseResultsItemCreatedByOneLastNameMax = 150

export const changeRequestsListResponseResultsItemCreatedByOneEmailMax = 254

export const changeRequestsListResponseResultsItemAppliedByOneDistinctIdMax = 200

export const changeRequestsListResponseResultsItemAppliedByOneFirstNameMax = 150

export const changeRequestsListResponseResultsItemAppliedByOneLastNameMax = 150

export const changeRequestsListResponseResultsItemAppliedByOneEmailMax = 254

export const ChangeRequestsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            action_key: zod.string(),
            action_version: zod.number(),
            resource_type: zod.string(),
            resource_id: zod.string().nullable(),
            intent: zod.unknown(),
            intent_display: zod.unknown(),
            policy_snapshot: zod.unknown(),
            validation_status: zod
                .enum(['valid', 'invalid', 'expired', 'stale'])
                .describe(
                    '* `valid` - Valid\n* `invalid` - Invalid\n* `expired` - Expired\n* `stale` - Stale (resource changed)'
                ),
            validation_errors: zod.unknown().nullable(),
            validated_at: zod.iso.datetime({}).nullable(),
            state: zod
                .enum(['pending', 'approved', 'applied', 'rejected', 'expired', 'failed'])
                .describe(
                    '* `pending` - Pending\n* `approved` - Approved (awaiting application)\n* `applied` - Applied\n* `rejected` - Rejected\n* `expired` - Expired\n* `failed` - Failed to apply'
                ),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(changeRequestsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(changeRequestsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(changeRequestsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(changeRequestsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            applied_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(changeRequestsListResponseResultsItemAppliedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(changeRequestsListResponseResultsItemAppliedByOneFirstNameMax).optional(),
                last_name: zod.string().max(changeRequestsListResponseResultsItemAppliedByOneLastNameMax).optional(),
                email: zod.email().max(changeRequestsListResponseResultsItemAppliedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            expires_at: zod.iso.datetime({}),
            applied_at: zod.iso.datetime({}).nullable(),
            apply_error: zod.string(),
            result_data: zod.unknown().nullable(),
            approvals: zod.array(zod.record(zod.string(), zod.unknown())),
            can_approve: zod.boolean().describe('Check if current user can approve this change request.'),
            can_cancel: zod.boolean(),
            is_requester: zod.boolean().describe('Check if current user is the requester.'),
            user_decision: zod
                .string()
                .nullable()
                .describe("Get the current user's approval decision if they have voted."),
        })
    ),
})

export const changeRequestsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const changeRequestsRetrieveResponseCreatedByOneFirstNameMax = 150

export const changeRequestsRetrieveResponseCreatedByOneLastNameMax = 150

export const changeRequestsRetrieveResponseCreatedByOneEmailMax = 254

export const changeRequestsRetrieveResponseAppliedByOneDistinctIdMax = 200

export const changeRequestsRetrieveResponseAppliedByOneFirstNameMax = 150

export const changeRequestsRetrieveResponseAppliedByOneLastNameMax = 150

export const changeRequestsRetrieveResponseAppliedByOneEmailMax = 254

export const ChangeRequestsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    action_key: zod.string(),
    action_version: zod.number(),
    resource_type: zod.string(),
    resource_id: zod.string().nullable(),
    intent: zod.unknown(),
    intent_display: zod.unknown(),
    policy_snapshot: zod.unknown(),
    validation_status: zod
        .enum(['valid', 'invalid', 'expired', 'stale'])
        .describe(
            '* `valid` - Valid\n* `invalid` - Invalid\n* `expired` - Expired\n* `stale` - Stale (resource changed)'
        ),
    validation_errors: zod.unknown().nullable(),
    validated_at: zod.iso.datetime({}).nullable(),
    state: zod
        .enum(['pending', 'approved', 'applied', 'rejected', 'expired', 'failed'])
        .describe(
            '* `pending` - Pending\n* `approved` - Approved (awaiting application)\n* `applied` - Applied\n* `rejected` - Rejected\n* `expired` - Expired\n* `failed` - Failed to apply'
        ),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(changeRequestsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(changeRequestsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(changeRequestsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(changeRequestsRetrieveResponseCreatedByOneEmailMax),
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
    applied_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(changeRequestsRetrieveResponseAppliedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(changeRequestsRetrieveResponseAppliedByOneFirstNameMax).optional(),
        last_name: zod.string().max(changeRequestsRetrieveResponseAppliedByOneLastNameMax).optional(),
        email: zod.email().max(changeRequestsRetrieveResponseAppliedByOneEmailMax),
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
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    expires_at: zod.iso.datetime({}),
    applied_at: zod.iso.datetime({}).nullable(),
    apply_error: zod.string(),
    result_data: zod.unknown().nullable(),
    approvals: zod.array(zod.record(zod.string(), zod.unknown())),
    can_approve: zod.boolean().describe('Check if current user can approve this change request.'),
    can_cancel: zod.boolean(),
    is_requester: zod.boolean().describe('Check if current user is the requester.'),
    user_decision: zod.string().nullable().describe("Get the current user's approval decision if they have voted."),
})

/**
 * Approve a change request.
If quorum is reached, automatically applies the change immediately.
 */
export const ChangeRequestsApproveCreateBody = /* @__PURE__ */ zod.object({})

export const changeRequestsApproveCreateResponseCreatedByOneDistinctIdMax = 200

export const changeRequestsApproveCreateResponseCreatedByOneFirstNameMax = 150

export const changeRequestsApproveCreateResponseCreatedByOneLastNameMax = 150

export const changeRequestsApproveCreateResponseCreatedByOneEmailMax = 254

export const changeRequestsApproveCreateResponseAppliedByOneDistinctIdMax = 200

export const changeRequestsApproveCreateResponseAppliedByOneFirstNameMax = 150

export const changeRequestsApproveCreateResponseAppliedByOneLastNameMax = 150

export const changeRequestsApproveCreateResponseAppliedByOneEmailMax = 254

export const ChangeRequestsApproveCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    action_key: zod.string(),
    action_version: zod.number(),
    resource_type: zod.string(),
    resource_id: zod.string().nullable(),
    intent: zod.unknown(),
    intent_display: zod.unknown(),
    policy_snapshot: zod.unknown(),
    validation_status: zod
        .enum(['valid', 'invalid', 'expired', 'stale'])
        .describe(
            '* `valid` - Valid\n* `invalid` - Invalid\n* `expired` - Expired\n* `stale` - Stale (resource changed)'
        ),
    validation_errors: zod.unknown().nullable(),
    validated_at: zod.iso.datetime({}).nullable(),
    state: zod
        .enum(['pending', 'approved', 'applied', 'rejected', 'expired', 'failed'])
        .describe(
            '* `pending` - Pending\n* `approved` - Approved (awaiting application)\n* `applied` - Applied\n* `rejected` - Rejected\n* `expired` - Expired\n* `failed` - Failed to apply'
        ),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(changeRequestsApproveCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(changeRequestsApproveCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(changeRequestsApproveCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(changeRequestsApproveCreateResponseCreatedByOneEmailMax),
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
    applied_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(changeRequestsApproveCreateResponseAppliedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(changeRequestsApproveCreateResponseAppliedByOneFirstNameMax).optional(),
        last_name: zod.string().max(changeRequestsApproveCreateResponseAppliedByOneLastNameMax).optional(),
        email: zod.email().max(changeRequestsApproveCreateResponseAppliedByOneEmailMax),
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
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    expires_at: zod.iso.datetime({}),
    applied_at: zod.iso.datetime({}).nullable(),
    apply_error: zod.string(),
    result_data: zod.unknown().nullable(),
    approvals: zod.array(zod.record(zod.string(), zod.unknown())),
    can_approve: zod.boolean().describe('Check if current user can approve this change request.'),
    can_cancel: zod.boolean(),
    is_requester: zod.boolean().describe('Check if current user is the requester.'),
    user_decision: zod.string().nullable().describe("Get the current user's approval decision if they have voted."),
})

/**
 * Cancel a change request.
Only the requester can cancel their own pending change request.
 */
export const ChangeRequestsCancelCreateBody = /* @__PURE__ */ zod.object({})

export const changeRequestsCancelCreateResponseCreatedByOneDistinctIdMax = 200

export const changeRequestsCancelCreateResponseCreatedByOneFirstNameMax = 150

export const changeRequestsCancelCreateResponseCreatedByOneLastNameMax = 150

export const changeRequestsCancelCreateResponseCreatedByOneEmailMax = 254

export const changeRequestsCancelCreateResponseAppliedByOneDistinctIdMax = 200

export const changeRequestsCancelCreateResponseAppliedByOneFirstNameMax = 150

export const changeRequestsCancelCreateResponseAppliedByOneLastNameMax = 150

export const changeRequestsCancelCreateResponseAppliedByOneEmailMax = 254

export const ChangeRequestsCancelCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    action_key: zod.string(),
    action_version: zod.number(),
    resource_type: zod.string(),
    resource_id: zod.string().nullable(),
    intent: zod.unknown(),
    intent_display: zod.unknown(),
    policy_snapshot: zod.unknown(),
    validation_status: zod
        .enum(['valid', 'invalid', 'expired', 'stale'])
        .describe(
            '* `valid` - Valid\n* `invalid` - Invalid\n* `expired` - Expired\n* `stale` - Stale (resource changed)'
        ),
    validation_errors: zod.unknown().nullable(),
    validated_at: zod.iso.datetime({}).nullable(),
    state: zod
        .enum(['pending', 'approved', 'applied', 'rejected', 'expired', 'failed'])
        .describe(
            '* `pending` - Pending\n* `approved` - Approved (awaiting application)\n* `applied` - Applied\n* `rejected` - Rejected\n* `expired` - Expired\n* `failed` - Failed to apply'
        ),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(changeRequestsCancelCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(changeRequestsCancelCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(changeRequestsCancelCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(changeRequestsCancelCreateResponseCreatedByOneEmailMax),
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
    applied_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(changeRequestsCancelCreateResponseAppliedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(changeRequestsCancelCreateResponseAppliedByOneFirstNameMax).optional(),
        last_name: zod.string().max(changeRequestsCancelCreateResponseAppliedByOneLastNameMax).optional(),
        email: zod.email().max(changeRequestsCancelCreateResponseAppliedByOneEmailMax),
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
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    expires_at: zod.iso.datetime({}),
    applied_at: zod.iso.datetime({}).nullable(),
    apply_error: zod.string(),
    result_data: zod.unknown().nullable(),
    approvals: zod.array(zod.record(zod.string(), zod.unknown())),
    can_approve: zod.boolean().describe('Check if current user can approve this change request.'),
    can_cancel: zod.boolean(),
    is_requester: zod.boolean().describe('Check if current user is the requester.'),
    user_decision: zod.string().nullable().describe("Get the current user's approval decision if they have voted."),
})

/**
 * Reject a change request.
 */
export const ChangeRequestsRejectCreateBody = /* @__PURE__ */ zod.object({})

export const changeRequestsRejectCreateResponseCreatedByOneDistinctIdMax = 200

export const changeRequestsRejectCreateResponseCreatedByOneFirstNameMax = 150

export const changeRequestsRejectCreateResponseCreatedByOneLastNameMax = 150

export const changeRequestsRejectCreateResponseCreatedByOneEmailMax = 254

export const changeRequestsRejectCreateResponseAppliedByOneDistinctIdMax = 200

export const changeRequestsRejectCreateResponseAppliedByOneFirstNameMax = 150

export const changeRequestsRejectCreateResponseAppliedByOneLastNameMax = 150

export const changeRequestsRejectCreateResponseAppliedByOneEmailMax = 254

export const ChangeRequestsRejectCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    action_key: zod.string(),
    action_version: zod.number(),
    resource_type: zod.string(),
    resource_id: zod.string().nullable(),
    intent: zod.unknown(),
    intent_display: zod.unknown(),
    policy_snapshot: zod.unknown(),
    validation_status: zod
        .enum(['valid', 'invalid', 'expired', 'stale'])
        .describe(
            '* `valid` - Valid\n* `invalid` - Invalid\n* `expired` - Expired\n* `stale` - Stale (resource changed)'
        ),
    validation_errors: zod.unknown().nullable(),
    validated_at: zod.iso.datetime({}).nullable(),
    state: zod
        .enum(['pending', 'approved', 'applied', 'rejected', 'expired', 'failed'])
        .describe(
            '* `pending` - Pending\n* `approved` - Approved (awaiting application)\n* `applied` - Applied\n* `rejected` - Rejected\n* `expired` - Expired\n* `failed` - Failed to apply'
        ),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(changeRequestsRejectCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(changeRequestsRejectCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(changeRequestsRejectCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(changeRequestsRejectCreateResponseCreatedByOneEmailMax),
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
    applied_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(changeRequestsRejectCreateResponseAppliedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(changeRequestsRejectCreateResponseAppliedByOneFirstNameMax).optional(),
        last_name: zod.string().max(changeRequestsRejectCreateResponseAppliedByOneLastNameMax).optional(),
        email: zod.email().max(changeRequestsRejectCreateResponseAppliedByOneEmailMax),
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
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    expires_at: zod.iso.datetime({}),
    applied_at: zod.iso.datetime({}).nullable(),
    apply_error: zod.string(),
    result_data: zod.unknown().nullable(),
    approvals: zod.array(zod.record(zod.string(), zod.unknown())),
    can_approve: zod.boolean().describe('Check if current user can approve this change request.'),
    can_cancel: zod.boolean(),
    is_requester: zod.boolean().describe('Check if current user is the requester.'),
    user_decision: zod.string().nullable().describe("Get the current user's approval decision if they have voted."),
})

export const membersListResponseResultsItemUserOneDistinctIdMax = 200

export const membersListResponseResultsItemUserOneFirstNameMax = 150

export const membersListResponseResultsItemUserOneLastNameMax = 150

export const membersListResponseResultsItemUserOneEmailMax = 254

export const MembersListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            user: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(membersListResponseResultsItemUserOneDistinctIdMax).nullish(),
                first_name: zod.string().max(membersListResponseResultsItemUserOneFirstNameMax).optional(),
                last_name: zod.string().max(membersListResponseResultsItemUserOneLastNameMax).optional(),
                email: zod.email().max(membersListResponseResultsItemUserOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            level: zod
                .union([zod.literal(1), zod.literal(8), zod.literal(15)])
                .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
                .optional(),
            joined_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            is_2fa_enabled: zod.boolean(),
            has_social_auth: zod.boolean(),
            last_login: zod.iso.datetime({}),
        })
    ),
})

export const MembersUpdateBody = /* @__PURE__ */ zod.object({
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
})

export const membersUpdateResponseUserOneDistinctIdMax = 200

export const membersUpdateResponseUserOneFirstNameMax = 150

export const membersUpdateResponseUserOneLastNameMax = 150

export const membersUpdateResponseUserOneEmailMax = 254

export const MembersUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(membersUpdateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(membersUpdateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(membersUpdateResponseUserOneLastNameMax).optional(),
        email: zod.email().max(membersUpdateResponseUserOneEmailMax),
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
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
    joined_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    is_2fa_enabled: zod.boolean(),
    has_social_auth: zod.boolean(),
    last_login: zod.iso.datetime({}),
})

export const MembersPartialUpdateBody = /* @__PURE__ */ zod.object({
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
})

export const membersPartialUpdateResponseUserOneDistinctIdMax = 200

export const membersPartialUpdateResponseUserOneFirstNameMax = 150

export const membersPartialUpdateResponseUserOneLastNameMax = 150

export const membersPartialUpdateResponseUserOneEmailMax = 254

export const MembersPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(membersPartialUpdateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(membersPartialUpdateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(membersPartialUpdateResponseUserOneLastNameMax).optional(),
        email: zod.email().max(membersPartialUpdateResponseUserOneEmailMax),
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
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
    joined_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    is_2fa_enabled: zod.boolean(),
    has_social_auth: zod.boolean(),
    last_login: zod.iso.datetime({}),
})

export const membersScopedApiKeysRetrieveResponseUserOneDistinctIdMax = 200

export const membersScopedApiKeysRetrieveResponseUserOneFirstNameMax = 150

export const membersScopedApiKeysRetrieveResponseUserOneLastNameMax = 150

export const membersScopedApiKeysRetrieveResponseUserOneEmailMax = 254

export const MembersScopedApiKeysRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(membersScopedApiKeysRetrieveResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(membersScopedApiKeysRetrieveResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(membersScopedApiKeysRetrieveResponseUserOneLastNameMax).optional(),
        email: zod.email().max(membersScopedApiKeysRetrieveResponseUserOneEmailMax),
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
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
    joined_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    is_2fa_enabled: zod.boolean(),
    has_social_auth: zod.boolean(),
    last_login: zod.iso.datetime({}),
})

export const rolesListResponseResultsItemNameMax = 200

export const rolesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const rolesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const rolesListResponseResultsItemCreatedByOneLastNameMax = 150

export const rolesListResponseResultsItemCreatedByOneEmailMax = 254

export const RolesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(rolesListResponseResultsItemNameMax),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(rolesListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(rolesListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(rolesListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(rolesListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            members: zod.array(zod.record(zod.string(), zod.unknown())).describe('Members assigned to this role'),
            is_default: zod.boolean(),
        })
    ),
})

export const rolesCreateBodyNameMax = 200

export const RolesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(rolesCreateBodyNameMax),
})

export const rolesRetrieveResponseNameMax = 200

export const rolesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const rolesRetrieveResponseCreatedByOneFirstNameMax = 150

export const rolesRetrieveResponseCreatedByOneLastNameMax = 150

export const rolesRetrieveResponseCreatedByOneEmailMax = 254

export const RolesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(rolesRetrieveResponseNameMax),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(rolesRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(rolesRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(rolesRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(rolesRetrieveResponseCreatedByOneEmailMax),
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
    members: zod.array(zod.record(zod.string(), zod.unknown())).describe('Members assigned to this role'),
    is_default: zod.boolean(),
})

export const rolesUpdateBodyNameMax = 200

export const RolesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(rolesUpdateBodyNameMax),
})

export const rolesUpdateResponseNameMax = 200

export const rolesUpdateResponseCreatedByOneDistinctIdMax = 200

export const rolesUpdateResponseCreatedByOneFirstNameMax = 150

export const rolesUpdateResponseCreatedByOneLastNameMax = 150

export const rolesUpdateResponseCreatedByOneEmailMax = 254

export const RolesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(rolesUpdateResponseNameMax),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(rolesUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(rolesUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(rolesUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(rolesUpdateResponseCreatedByOneEmailMax),
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
    members: zod.array(zod.record(zod.string(), zod.unknown())).describe('Members assigned to this role'),
    is_default: zod.boolean(),
})

export const rolesPartialUpdateBodyNameMax = 200

export const RolesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(rolesPartialUpdateBodyNameMax).optional(),
})

export const rolesPartialUpdateResponseNameMax = 200

export const rolesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const rolesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const rolesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const rolesPartialUpdateResponseCreatedByOneEmailMax = 254

export const RolesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(rolesPartialUpdateResponseNameMax),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(rolesPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(rolesPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(rolesPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(rolesPartialUpdateResponseCreatedByOneEmailMax),
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
    members: zod.array(zod.record(zod.string(), zod.unknown())).describe('Members assigned to this role'),
    is_default: zod.boolean(),
})

export const rolesRoleMembershipsListResponseResultsItemOrganizationMemberOneUserOneDistinctIdMax = 200

export const rolesRoleMembershipsListResponseResultsItemOrganizationMemberOneUserOneFirstNameMax = 150

export const rolesRoleMembershipsListResponseResultsItemOrganizationMemberOneUserOneLastNameMax = 150

export const rolesRoleMembershipsListResponseResultsItemOrganizationMemberOneUserOneEmailMax = 254

export const rolesRoleMembershipsListResponseResultsItemUserOneDistinctIdMax = 200

export const rolesRoleMembershipsListResponseResultsItemUserOneFirstNameMax = 150

export const rolesRoleMembershipsListResponseResultsItemUserOneLastNameMax = 150

export const rolesRoleMembershipsListResponseResultsItemUserOneEmailMax = 254

export const RolesRoleMembershipsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            role_id: zod.uuid(),
            organization_member: zod.object({
                id: zod.uuid(),
                user: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(rolesRoleMembershipsListResponseResultsItemOrganizationMemberOneUserOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(rolesRoleMembershipsListResponseResultsItemOrganizationMemberOneUserOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(rolesRoleMembershipsListResponseResultsItemOrganizationMemberOneUserOneLastNameMax)
                        .optional(),
                    email: zod
                        .email()
                        .max(rolesRoleMembershipsListResponseResultsItemOrganizationMemberOneUserOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                level: zod
                    .union([zod.literal(1), zod.literal(8), zod.literal(15)])
                    .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
                    .optional(),
                joined_at: zod.iso.datetime({}),
                updated_at: zod.iso.datetime({}),
                is_2fa_enabled: zod.boolean(),
                has_social_auth: zod.boolean(),
                last_login: zod.iso.datetime({}),
            }),
            user: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(rolesRoleMembershipsListResponseResultsItemUserOneDistinctIdMax)
                    .nullish(),
                first_name: zod.string().max(rolesRoleMembershipsListResponseResultsItemUserOneFirstNameMax).optional(),
                last_name: zod.string().max(rolesRoleMembershipsListResponseResultsItemUserOneLastNameMax).optional(),
                email: zod.email().max(rolesRoleMembershipsListResponseResultsItemUserOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            joined_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            user_uuid: zod.uuid(),
        })
    ),
})

export const RolesRoleMembershipsCreateBody = /* @__PURE__ */ zod.object({
    user_uuid: zod.uuid(),
})

export const rolesRoleMembershipsRetrieveResponseOrganizationMemberOneUserOneDistinctIdMax = 200

export const rolesRoleMembershipsRetrieveResponseOrganizationMemberOneUserOneFirstNameMax = 150

export const rolesRoleMembershipsRetrieveResponseOrganizationMemberOneUserOneLastNameMax = 150

export const rolesRoleMembershipsRetrieveResponseOrganizationMemberOneUserOneEmailMax = 254

export const rolesRoleMembershipsRetrieveResponseUserOneDistinctIdMax = 200

export const rolesRoleMembershipsRetrieveResponseUserOneFirstNameMax = 150

export const rolesRoleMembershipsRetrieveResponseUserOneLastNameMax = 150

export const rolesRoleMembershipsRetrieveResponseUserOneEmailMax = 254

export const RolesRoleMembershipsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    role_id: zod.uuid(),
    organization_member: zod.object({
        id: zod.uuid(),
        user: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(rolesRoleMembershipsRetrieveResponseOrganizationMemberOneUserOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(rolesRoleMembershipsRetrieveResponseOrganizationMemberOneUserOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(rolesRoleMembershipsRetrieveResponseOrganizationMemberOneUserOneLastNameMax)
                .optional(),
            email: zod.email().max(rolesRoleMembershipsRetrieveResponseOrganizationMemberOneUserOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        level: zod
            .union([zod.literal(1), zod.literal(8), zod.literal(15)])
            .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
            .optional(),
        joined_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        is_2fa_enabled: zod.boolean(),
        has_social_auth: zod.boolean(),
        last_login: zod.iso.datetime({}),
    }),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(rolesRoleMembershipsRetrieveResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(rolesRoleMembershipsRetrieveResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(rolesRoleMembershipsRetrieveResponseUserOneLastNameMax).optional(),
        email: zod.email().max(rolesRoleMembershipsRetrieveResponseUserOneEmailMax),
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
    joined_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    user_uuid: zod.uuid(),
})

export const activityLogListResponseUserDistinctIdMax = 200

export const activityLogListResponseUserFirstNameMax = 150

export const activityLogListResponseUserLastNameMax = 150

export const activityLogListResponseUserEmailMax = 254

export const activityLogListResponseActivityMax = 79

export const activityLogListResponseItemIdMax = 72

export const activityLogListResponseScopeMax = 79

export const ActivityLogListResponseItem = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(activityLogListResponseUserDistinctIdMax).nullish(),
        first_name: zod.string().max(activityLogListResponseUserFirstNameMax).optional(),
        last_name: zod.string().max(activityLogListResponseUserLastNameMax).optional(),
        email: zod.email().max(activityLogListResponseUserEmailMax),
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
    unread: zod.boolean().describe("is the date of this log item newer than the user's bookmark"),
    organization_id: zod.uuid().nullish(),
    was_impersonated: zod.boolean().nullish(),
    is_system: zod.boolean().nullish(),
    activity: zod.string().max(activityLogListResponseActivityMax),
    item_id: zod.string().max(activityLogListResponseItemIdMax).nullish(),
    scope: zod.string().max(activityLogListResponseScopeMax),
    detail: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}).optional(),
})
export const ActivityLogListResponse = /* @__PURE__ */ zod.array(ActivityLogListResponseItem)

export const advancedActivityLogsListResponseUserDistinctIdMax = 200

export const advancedActivityLogsListResponseUserFirstNameMax = 150

export const advancedActivityLogsListResponseUserLastNameMax = 150

export const advancedActivityLogsListResponseUserEmailMax = 254

export const advancedActivityLogsListResponseActivityMax = 79

export const advancedActivityLogsListResponseItemIdMax = 72

export const advancedActivityLogsListResponseScopeMax = 79

export const AdvancedActivityLogsListResponseItem = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(advancedActivityLogsListResponseUserDistinctIdMax).nullish(),
        first_name: zod.string().max(advancedActivityLogsListResponseUserFirstNameMax).optional(),
        last_name: zod.string().max(advancedActivityLogsListResponseUserLastNameMax).optional(),
        email: zod.email().max(advancedActivityLogsListResponseUserEmailMax),
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
    unread: zod.boolean().describe("is the date of this log item newer than the user's bookmark"),
    organization_id: zod.uuid().nullish(),
    was_impersonated: zod.boolean().nullish(),
    is_system: zod.boolean().nullish(),
    activity: zod.string().max(advancedActivityLogsListResponseActivityMax),
    item_id: zod.string().max(advancedActivityLogsListResponseItemIdMax).nullish(),
    scope: zod.string().max(advancedActivityLogsListResponseScopeMax),
    detail: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}).optional(),
})
export const AdvancedActivityLogsListResponse = /* @__PURE__ */ zod.array(AdvancedActivityLogsListResponseItem)

export const AdvancedActivityLogsAvailableFiltersRetrieveResponse = /* @__PURE__ */ zod.object({
    static_filters: zod
        .object({
            users: zod.array(zod.record(zod.string(), zod.unknown())).describe('Users who have logged activity.'),
            scopes: zod.array(zod.record(zod.string(), zod.unknown())).describe('Available activity scopes.'),
            activities: zod.array(zod.record(zod.string(), zod.unknown())).describe('Available activity types.'),
        })
        .describe('Pre-computed filter options for scopes, activities, and users.'),
    detail_fields: zod
        .record(zod.string(), zod.unknown())
        .describe('Discovered detail fields and their value distributions.'),
})

export const advancedActivityLogsExportCreateBodyUserDistinctIdMax = 200

export const advancedActivityLogsExportCreateBodyUserFirstNameMax = 150

export const advancedActivityLogsExportCreateBodyUserLastNameMax = 150

export const advancedActivityLogsExportCreateBodyUserEmailMax = 254

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
    activity: zod.string().max(advancedActivityLogsExportCreateBodyActivityMax),
    item_id: zod.string().max(advancedActivityLogsExportCreateBodyItemIdMax).nullish(),
    scope: zod.string().max(advancedActivityLogsExportCreateBodyScopeMax),
    detail: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}).optional(),
})

export const advancedActivityLogsExportCreateResponseUserDistinctIdMax = 200

export const advancedActivityLogsExportCreateResponseUserFirstNameMax = 150

export const advancedActivityLogsExportCreateResponseUserLastNameMax = 150

export const advancedActivityLogsExportCreateResponseUserEmailMax = 254

export const advancedActivityLogsExportCreateResponseActivityMax = 79

export const advancedActivityLogsExportCreateResponseItemIdMax = 72

export const advancedActivityLogsExportCreateResponseScopeMax = 79

export const AdvancedActivityLogsExportCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(advancedActivityLogsExportCreateResponseUserDistinctIdMax).nullish(),
        first_name: zod.string().max(advancedActivityLogsExportCreateResponseUserFirstNameMax).optional(),
        last_name: zod.string().max(advancedActivityLogsExportCreateResponseUserLastNameMax).optional(),
        email: zod.email().max(advancedActivityLogsExportCreateResponseUserEmailMax),
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
    unread: zod.boolean().describe("is the date of this log item newer than the user's bookmark"),
    organization_id: zod.uuid().nullish(),
    was_impersonated: zod.boolean().nullish(),
    is_system: zod.boolean().nullish(),
    activity: zod.string().max(advancedActivityLogsExportCreateResponseActivityMax),
    item_id: zod.string().max(advancedActivityLogsExportCreateResponseItemIdMax).nullish(),
    scope: zod.string().max(advancedActivityLogsExportCreateResponseScopeMax),
    detail: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}).optional(),
})

export const commentsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const commentsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const commentsListResponseResultsItemCreatedByOneLastNameMax = 150

export const commentsListResponseResultsItemCreatedByOneEmailMax = 254

export const commentsListResponseResultsItemItemIdMax = 72

export const commentsListResponseResultsItemScopeMax = 79

export const CommentsListResponse = /* @__PURE__ */ zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(commentsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(commentsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(commentsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(commentsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            deleted: zod.boolean().nullish(),
            mentions: zod.array(zod.number()).optional(),
            slug: zod.string().optional(),
            content: zod.string().nullish(),
            rich_content: zod.unknown().nullish(),
            version: zod.number(),
            created_at: zod.iso.datetime({}),
            item_id: zod.string().max(commentsListResponseResultsItemItemIdMax).nullish(),
            item_context: zod.unknown().nullish(),
            scope: zod.string().max(commentsListResponseResultsItemScopeMax),
            source_comment: zod.uuid().nullish(),
        })
    ),
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

export const commentsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const commentsRetrieveResponseCreatedByOneFirstNameMax = 150

export const commentsRetrieveResponseCreatedByOneLastNameMax = 150

export const commentsRetrieveResponseCreatedByOneEmailMax = 254

export const commentsRetrieveResponseItemIdMax = 72

export const commentsRetrieveResponseScopeMax = 79

export const CommentsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(commentsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(commentsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(commentsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(commentsRetrieveResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().nullish(),
    mentions: zod.array(zod.number()).optional(),
    slug: zod.string().optional(),
    content: zod.string().nullish(),
    rich_content: zod.unknown().nullish(),
    version: zod.number(),
    created_at: zod.iso.datetime({}),
    item_id: zod.string().max(commentsRetrieveResponseItemIdMax).nullish(),
    item_context: zod.unknown().nullish(),
    scope: zod.string().max(commentsRetrieveResponseScopeMax),
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

export const commentsUpdateResponseCreatedByOneDistinctIdMax = 200

export const commentsUpdateResponseCreatedByOneFirstNameMax = 150

export const commentsUpdateResponseCreatedByOneLastNameMax = 150

export const commentsUpdateResponseCreatedByOneEmailMax = 254

export const commentsUpdateResponseItemIdMax = 72

export const commentsUpdateResponseScopeMax = 79

export const CommentsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(commentsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(commentsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(commentsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(commentsUpdateResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().nullish(),
    mentions: zod.array(zod.number()).optional(),
    slug: zod.string().optional(),
    content: zod.string().nullish(),
    rich_content: zod.unknown().nullish(),
    version: zod.number(),
    created_at: zod.iso.datetime({}),
    item_id: zod.string().max(commentsUpdateResponseItemIdMax).nullish(),
    item_context: zod.unknown().nullish(),
    scope: zod.string().max(commentsUpdateResponseScopeMax),
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

export const commentsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const commentsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const commentsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const commentsPartialUpdateResponseCreatedByOneEmailMax = 254

export const commentsPartialUpdateResponseItemIdMax = 72

export const commentsPartialUpdateResponseScopeMax = 79

export const CommentsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(commentsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(commentsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(commentsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(commentsPartialUpdateResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().nullish(),
    mentions: zod.array(zod.number()).optional(),
    slug: zod.string().optional(),
    content: zod.string().nullish(),
    rich_content: zod.unknown().nullish(),
    version: zod.number(),
    created_at: zod.iso.datetime({}),
    item_id: zod.string().max(commentsPartialUpdateResponseItemIdMax).nullish(),
    item_context: zod.unknown().nullish(),
    scope: zod.string().max(commentsPartialUpdateResponseScopeMax),
    source_comment: zod.uuid().nullish(),
})
