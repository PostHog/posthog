/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const ErrorTrackingAssignmentRuleApi = zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullable(),
    order_key: zod.number(),
    disabled_data: zod.unknown(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type ErrorTrackingAssignmentRuleApi = zod.input<typeof ErrorTrackingAssignmentRuleApi>
export type ErrorTrackingAssignmentRuleApiOutput = zod.output<typeof ErrorTrackingAssignmentRuleApi>

export const PaginatedErrorTrackingAssignmentRuleListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingAssignmentRuleApi),
})

export type PaginatedErrorTrackingAssignmentRuleListApi = zod.input<typeof PaginatedErrorTrackingAssignmentRuleListApi>
export type PaginatedErrorTrackingAssignmentRuleListApiOutput = zod.output<
    typeof PaginatedErrorTrackingAssignmentRuleListApi
>

export const PropertyGroupFilterValueApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PropertyGroupFilterValueApi = zod.input<typeof PropertyGroupFilterValueApi>
export type PropertyGroupFilterValueApiOutput = zod.output<typeof PropertyGroupFilterValueApi>

export const AssigneeTypeEnumApi = zod.enum(['user', 'role']).describe('\* `user` - user\n\* `role` - role')

export type AssigneeTypeEnumApi = zod.input<typeof AssigneeTypeEnumApi>
export type AssigneeTypeEnumApiOutput = zod.output<typeof AssigneeTypeEnumApi>

export const ErrorTrackingAssignmentRuleAssigneeRequestApi = zod.object({
    type: AssigneeTypeEnumApi.describe(
        'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n\* `user` - user\n\* `role` - role'
    ),
    id: zod
        .union([zod.number(), zod.uuid()])
        .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
})

export type ErrorTrackingAssignmentRuleAssigneeRequestApi = zod.input<
    typeof ErrorTrackingAssignmentRuleAssigneeRequestApi
>
export type ErrorTrackingAssignmentRuleAssigneeRequestApiOutput = zod.output<
    typeof ErrorTrackingAssignmentRuleAssigneeRequestApi
>

export const errorTrackingAssignmentRuleCreateRequestApiOrderKeyDefault = 0

export const ErrorTrackingAssignmentRuleCreateRequestApi = zod.object({
    filters: PropertyGroupFilterValueApi.describe(
        'Property-group filters that define when this rule matches incoming error events.'
    ),
    assignee: ErrorTrackingAssignmentRuleAssigneeRequestApi.describe('User or role to assign matching issues to.'),
    order_key: zod
        .number()
        .default(errorTrackingAssignmentRuleCreateRequestApiOrderKeyDefault)
        .describe(
            'Evaluation priority among rules; lower is evaluated first and the first matching rule wins. Defaults to 0. Pass distinct ascending values when creating several rules at once to give them a deterministic order.'
        ),
})

export type ErrorTrackingAssignmentRuleCreateRequestApi = zod.input<typeof ErrorTrackingAssignmentRuleCreateRequestApi>
export type ErrorTrackingAssignmentRuleCreateRequestApiOutput = zod.output<
    typeof ErrorTrackingAssignmentRuleCreateRequestApi
>

export const ErrorTrackingAssignmentRuleUpdateRequestApi = zod.object({
    filters: zod
        .union([PropertyGroupFilterValueApi, zod.null()])
        .optional()
        .describe('Property-group filters that define when this rule matches incoming error events.'),
    assignee: zod
        .union([ErrorTrackingAssignmentRuleAssigneeRequestApi, zod.null()])
        .optional()
        .describe('User or role to assign matching issues to.'),
})

export type ErrorTrackingAssignmentRuleUpdateRequestApi = zod.input<typeof ErrorTrackingAssignmentRuleUpdateRequestApi>
export type ErrorTrackingAssignmentRuleUpdateRequestApiOutput = zod.output<
    typeof ErrorTrackingAssignmentRuleUpdateRequestApi
>

export const PatchedErrorTrackingAssignmentRuleUpdateRequestApi = zod.object({
    filters: zod
        .union([PropertyGroupFilterValueApi, zod.null()])
        .optional()
        .describe('Property-group filters that define when this rule matches incoming error events.'),
    assignee: zod
        .union([ErrorTrackingAssignmentRuleAssigneeRequestApi, zod.null()])
        .optional()
        .describe('User or role to assign matching issues to.'),
})

export type PatchedErrorTrackingAssignmentRuleUpdateRequestApi = zod.input<
    typeof PatchedErrorTrackingAssignmentRuleUpdateRequestApi
>
export type PatchedErrorTrackingAssignmentRuleUpdateRequestApiOutput = zod.output<
    typeof PatchedErrorTrackingAssignmentRuleUpdateRequestApi
>

export const PatchedErrorTrackingAssignmentRuleApi = zod.object({
    id: zod.uuid().optional(),
    filters: zod.unknown().optional(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullish(),
    order_key: zod.number().optional(),
    disabled_data: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedErrorTrackingAssignmentRuleApi = zod.input<typeof PatchedErrorTrackingAssignmentRuleApi>
export type PatchedErrorTrackingAssignmentRuleApiOutput = zod.output<typeof PatchedErrorTrackingAssignmentRuleApi>

export const ErrorTrackingBypassRuleApi = zod.object({
    id: zod.uuid().describe('Unique identifier of the bypass rule.'),
    filters: zod
        .unknown()
        .describe('Property-group filters that define which incoming error events bypass rate limiting.'),
    order_key: zod
        .number()
        .describe("Position of the rule in the team's ordered list. Rules are evaluated greedily in ascending order."),
    disabled_data: zod
        .unknown()
        .describe(
            'Populated when the rule has been automatically disabled (for example, after its filters failed to evaluate during ingestion). Null while the rule is active.'
        ),
    created_at: zod.iso.datetime({ offset: true }).describe('When the rule was created.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When the rule was last updated.'),
})

export type ErrorTrackingBypassRuleApi = zod.input<typeof ErrorTrackingBypassRuleApi>
export type ErrorTrackingBypassRuleApiOutput = zod.output<typeof ErrorTrackingBypassRuleApi>

export const PaginatedErrorTrackingBypassRuleListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingBypassRuleApi),
})

export type PaginatedErrorTrackingBypassRuleListApi = zod.input<typeof PaginatedErrorTrackingBypassRuleListApi>
export type PaginatedErrorTrackingBypassRuleListApiOutput = zod.output<typeof PaginatedErrorTrackingBypassRuleListApi>

export const ErrorTrackingBypassRuleCreateRequestApi = zod.object({
    filters: PropertyGroupFilterValueApi.describe(
        'Property-group filters that define which incoming error events bypass rate limiting. Must contain at least one filter — empty rules are rejected. To stop rate limiting entirely, adjust the rate limit settings instead of creating a match-all bypass rule.'
    ),
})

export type ErrorTrackingBypassRuleCreateRequestApi = zod.input<typeof ErrorTrackingBypassRuleCreateRequestApi>
export type ErrorTrackingBypassRuleCreateRequestApiOutput = zod.output<typeof ErrorTrackingBypassRuleCreateRequestApi>

export const ErrorTrackingBypassRuleUpdateRequestApi = zod.object({
    filters: PropertyGroupFilterValueApi.optional().describe(
        'Property-group filters that define which incoming error events bypass rate limiting. Must contain at least one filter. Omit to preserve the existing filters.'
    ),
})

export type ErrorTrackingBypassRuleUpdateRequestApi = zod.input<typeof ErrorTrackingBypassRuleUpdateRequestApi>
export type ErrorTrackingBypassRuleUpdateRequestApiOutput = zod.output<typeof ErrorTrackingBypassRuleUpdateRequestApi>

export const PatchedErrorTrackingBypassRuleUpdateRequestApi = zod.object({
    filters: PropertyGroupFilterValueApi.optional().describe(
        'Property-group filters that define which incoming error events bypass rate limiting. Must contain at least one filter. Omit to preserve the existing filters.'
    ),
})

export type PatchedErrorTrackingBypassRuleUpdateRequestApi = zod.input<
    typeof PatchedErrorTrackingBypassRuleUpdateRequestApi
>
export type PatchedErrorTrackingBypassRuleUpdateRequestApiOutput = zod.output<
    typeof PatchedErrorTrackingBypassRuleUpdateRequestApi
>

export const PatchedErrorTrackingBypassRuleApi = zod.object({
    id: zod.uuid().optional().describe('Unique identifier of the bypass rule.'),
    filters: zod
        .unknown()
        .optional()
        .describe('Property-group filters that define which incoming error events bypass rate limiting.'),
    order_key: zod
        .number()
        .optional()
        .describe("Position of the rule in the team's ordered list. Rules are evaluated greedily in ascending order."),
    disabled_data: zod
        .unknown()
        .optional()
        .describe(
            'Populated when the rule has been automatically disabled (for example, after its filters failed to evaluate during ingestion). Null while the rule is active.'
        ),
    created_at: zod.iso.datetime({ offset: true }).optional().describe('When the rule was created.'),
    updated_at: zod.iso.datetime({ offset: true }).optional().describe('When the rule was last updated.'),
})

export type PatchedErrorTrackingBypassRuleApi = zod.input<typeof PatchedErrorTrackingBypassRuleApi>
export type PatchedErrorTrackingBypassRuleApiOutput = zod.output<typeof PatchedErrorTrackingBypassRuleApi>

export const ErrorTrackingExternalReferenceIntegrationResultApi = zod.object({
    id: zod.number().describe('ID of the integration backing this external reference.'),
    kind: zod.string().describe("Integration provider, e.g. 'github', 'gitlab', 'linear', or 'jira'."),
    display_name: zod.string().describe('Human-readable name of the connected integration.'),
})

export type ErrorTrackingExternalReferenceIntegrationResultApi = zod.input<
    typeof ErrorTrackingExternalReferenceIntegrationResultApi
>
export type ErrorTrackingExternalReferenceIntegrationResultApiOutput = zod.output<
    typeof ErrorTrackingExternalReferenceIntegrationResultApi
>

export const ErrorTrackingExternalReferenceResultApi = zod.object({
    id: zod.uuid().describe('Unique ID of the external reference.'),
    integration: ErrorTrackingExternalReferenceIntegrationResultApi.describe(
        'The connected integration this reference was created through.'
    ),
    integration_id: zod
        .number()
        .describe(
            "ID of the connected integration to create the external issue with. List the project's integrations to find the right ID and its kind (one of 'github', 'gitlab', 'linear', 'jira')."
        ),
    config: zod
        .record(zod.string(), zod.string())
        .describe(
            'Provider-specific fields describing the external issue to create. Required keys depend on the integration kind: github -> {repository, title, body}; gitlab -> {title, body}; linear -> {team_id, title, description}; jira -> {project_key, title, description}. Examples: github {\"repository\":\"posthog\",\"title\":\"Checkout TypeError\",\"body\":\"Stack trace\"}; linear {\"team_id\":\"team-id\",\"title\":\"Checkout TypeError\",\"description\":\"Stack trace\"}; jira {\"project_key\":\"ENG\",\"title\":\"Checkout TypeError\",\"description\":\"Stack trace\"}.'
        ),
    issue: zod.uuid().describe('ID of the error tracking issue to link the reference to.'),
    external_url: zod.string().describe("URL of the linked external issue in the provider's system."),
})

export type ErrorTrackingExternalReferenceResultApi = zod.input<typeof ErrorTrackingExternalReferenceResultApi>
export type ErrorTrackingExternalReferenceResultApiOutput = zod.output<typeof ErrorTrackingExternalReferenceResultApi>

export const PaginatedErrorTrackingExternalReferenceResultListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingExternalReferenceResultApi),
})

export type PaginatedErrorTrackingExternalReferenceResultListApi = zod.input<
    typeof PaginatedErrorTrackingExternalReferenceResultListApi
>
export type PaginatedErrorTrackingExternalReferenceResultListApiOutput = zod.output<
    typeof PaginatedErrorTrackingExternalReferenceResultListApi
>

export const ErrorTrackingFingerprintApi = zod.object({
    id: zod.uuid().describe('Unique ID of the fingerprint record.'),
    fingerprint: zod.string().describe('The fingerprint value.'),
    issue_id: zod.uuid().describe('ID of the issue this fingerprint currently belongs to.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the fingerprint record was created.'),
})

export type ErrorTrackingFingerprintApi = zod.input<typeof ErrorTrackingFingerprintApi>
export type ErrorTrackingFingerprintApiOutput = zod.output<typeof ErrorTrackingFingerprintApi>

export const PaginatedErrorTrackingFingerprintListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingFingerprintApi),
})

export type PaginatedErrorTrackingFingerprintListApi = zod.input<typeof PaginatedErrorTrackingFingerprintListApi>
export type PaginatedErrorTrackingFingerprintListApiOutput = zod.output<typeof PaginatedErrorTrackingFingerprintListApi>

export const GitProviderFileLinkResolveResponseApi = zod.object({
    found: zod.boolean().describe('Whether a matching file URL was found.'),
    url: zod.string().optional().describe('Resolved URL for the matching file.'),
    error: zod.string().optional().describe('Error message when input parameters are invalid.'),
})

export type GitProviderFileLinkResolveResponseApi = zod.input<typeof GitProviderFileLinkResolveResponseApi>
export type GitProviderFileLinkResolveResponseApiOutput = zod.output<typeof GitProviderFileLinkResolveResponseApi>

export const ErrorTrackingGroupingRuleApi = zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullable(),
    description: zod.string().nullable(),
    issue: zod.record(zod.string(), zod.string()).nullable().describe('Issue linked to this rule'),
    order_key: zod.number(),
    disabled_data: zod.unknown(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type ErrorTrackingGroupingRuleApi = zod.input<typeof ErrorTrackingGroupingRuleApi>
export type ErrorTrackingGroupingRuleApiOutput = zod.output<typeof ErrorTrackingGroupingRuleApi>

export const ErrorTrackingGroupingRuleListResponseApi = zod.object({
    results: zod.array(ErrorTrackingGroupingRuleApi),
})

export type ErrorTrackingGroupingRuleListResponseApi = zod.input<typeof ErrorTrackingGroupingRuleListResponseApi>
export type ErrorTrackingGroupingRuleListResponseApiOutput = zod.output<typeof ErrorTrackingGroupingRuleListResponseApi>

export const ErrorTrackingGroupingRuleAssigneeRequestApi = zod.object({
    type: AssigneeTypeEnumApi.describe(
        'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n\* `user` - user\n\* `role` - role'
    ),
    id: zod
        .union([zod.number(), zod.uuid()])
        .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
})

export type ErrorTrackingGroupingRuleAssigneeRequestApi = zod.input<typeof ErrorTrackingGroupingRuleAssigneeRequestApi>
export type ErrorTrackingGroupingRuleAssigneeRequestApiOutput = zod.output<
    typeof ErrorTrackingGroupingRuleAssigneeRequestApi
>

export const ErrorTrackingGroupingRuleCreateRequestApi = zod.object({
    filters: PropertyGroupFilterValueApi.describe(
        'Property-group filters that define which exceptions should be grouped into the same issue.'
    ),
    assignee: zod
        .union([ErrorTrackingGroupingRuleAssigneeRequestApi, zod.null()])
        .optional()
        .describe('Optional user or role to assign to issues created by this grouping rule.'),
    description: zod
        .string()
        .nullish()
        .describe('Optional human-readable description of what this grouping rule is for.'),
})

export type ErrorTrackingGroupingRuleCreateRequestApi = zod.input<typeof ErrorTrackingGroupingRuleCreateRequestApi>
export type ErrorTrackingGroupingRuleCreateRequestApiOutput = zod.output<
    typeof ErrorTrackingGroupingRuleCreateRequestApi
>

export const ErrorTrackingGroupingRuleUpdateRequestApi = zod.object({
    filters: zod
        .union([PropertyGroupFilterValueApi, zod.null()])
        .optional()
        .describe(
            'Property-group filters that define which exceptions should be grouped into the same issue. Omit to preserve the existing filters.'
        ),
})

export type ErrorTrackingGroupingRuleUpdateRequestApi = zod.input<typeof ErrorTrackingGroupingRuleUpdateRequestApi>
export type ErrorTrackingGroupingRuleUpdateRequestApiOutput = zod.output<
    typeof ErrorTrackingGroupingRuleUpdateRequestApi
>

export const PatchedErrorTrackingGroupingRuleUpdateRequestApi = zod.object({
    filters: zod
        .union([PropertyGroupFilterValueApi, zod.null()])
        .optional()
        .describe(
            'Property-group filters that define which exceptions should be grouped into the same issue. Omit to preserve the existing filters.'
        ),
})

export type PatchedErrorTrackingGroupingRuleUpdateRequestApi = zod.input<
    typeof PatchedErrorTrackingGroupingRuleUpdateRequestApi
>
export type PatchedErrorTrackingGroupingRuleUpdateRequestApiOutput = zod.output<
    typeof PatchedErrorTrackingGroupingRuleUpdateRequestApi
>

export const PatchedErrorTrackingGroupingRuleApi = zod.object({
    id: zod.uuid().optional(),
    filters: zod.unknown().optional(),
    assignee: zod
        .object({
            type: zod.enum(['user', 'role']).optional(),
            id: zod.union([zod.number(), zod.uuid()]).optional(),
        })
        .nullish(),
    description: zod.string().nullish(),
    issue: zod.record(zod.string(), zod.string()).nullish().describe('Issue linked to this rule'),
    order_key: zod.number().optional(),
    disabled_data: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedErrorTrackingGroupingRuleApi = zod.input<typeof PatchedErrorTrackingGroupingRuleApi>
export type PatchedErrorTrackingGroupingRuleApiOutput = zod.output<typeof PatchedErrorTrackingGroupingRuleApi>

export const ErrorTrackingIssueAssigneeReadApi = zod.object({
    id: zod.union([zod.number(), zod.string(), zod.null()]),
    type: zod.string(),
})

export type ErrorTrackingIssueAssigneeReadApi = zod.input<typeof ErrorTrackingIssueAssigneeReadApi>
export type ErrorTrackingIssueAssigneeReadApiOutput = zod.output<typeof ErrorTrackingIssueAssigneeReadApi>

export const ErrorTrackingIssueCohortReadApi = zod.object({
    id: zod.number(),
    name: zod.string(),
})

export type ErrorTrackingIssueCohortReadApi = zod.input<typeof ErrorTrackingIssueCohortReadApi>
export type ErrorTrackingIssueCohortReadApiOutput = zod.output<typeof ErrorTrackingIssueCohortReadApi>

export const ErrorTrackingIssueReadApi = zod
    .object({
        id: zod.uuid(),
        status: zod.string(),
        name: zod.string().nullable(),
        description: zod.string().nullable(),
        first_seen: zod.iso.datetime({ offset: true }).nullable(),
        assignee: zod.union([ErrorTrackingIssueAssigneeReadApi, zod.null()]),
        external_issues: zod.array(ErrorTrackingExternalReferenceResultApi),
        cohort: zod.union([ErrorTrackingIssueCohortReadApi, zod.null()]),
    })
    .describe('Read-only serializer for issue contract types returned by the facade.')

export type ErrorTrackingIssueReadApi = zod.input<typeof ErrorTrackingIssueReadApi>
export type ErrorTrackingIssueReadApiOutput = zod.output<typeof ErrorTrackingIssueReadApi>

export const PaginatedErrorTrackingIssueReadListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingIssueReadApi),
})

export type PaginatedErrorTrackingIssueReadListApi = zod.input<typeof PaginatedErrorTrackingIssueReadListApi>
export type PaginatedErrorTrackingIssueReadListApiOutput = zod.output<typeof PaginatedErrorTrackingIssueReadListApi>

export const ErrorTrackingIssueWriteStatusEnumApi = zod
    .enum(['active', 'resolved', 'suppressed'])
    .describe('\* `active` - active\n\* `resolved` - resolved\n\* `suppressed` - suppressed')

export type ErrorTrackingIssueWriteStatusEnumApi = zod.input<typeof ErrorTrackingIssueWriteStatusEnumApi>
export type ErrorTrackingIssueWriteStatusEnumApiOutput = zod.output<typeof ErrorTrackingIssueWriteStatusEnumApi>

export const ErrorTrackingIssueWriteApi = zod.object({
    status: ErrorTrackingIssueWriteStatusEnumApi.optional().describe(
        'Issue status to set. Deprecated archived and pending_release values are rejected.\n\n\* `active` - active\n\* `resolved` - resolved\n\* `suppressed` - suppressed'
    ),
    name: zod.string().nullish().describe('Optional issue display name.'),
    description: zod.string().nullish().describe('Optional issue description.'),
})

export type ErrorTrackingIssueWriteApi = zod.input<typeof ErrorTrackingIssueWriteApi>
export type ErrorTrackingIssueWriteApiOutput = zod.output<typeof ErrorTrackingIssueWriteApi>

export const PatchedErrorTrackingIssueWriteApi = zod.object({
    status: ErrorTrackingIssueWriteStatusEnumApi.optional().describe(
        'Issue status to set. Deprecated archived and pending_release values are rejected.\n\n\* `active` - active\n\* `resolved` - resolved\n\* `suppressed` - suppressed'
    ),
    name: zod.string().nullish().describe('Optional issue display name.'),
    description: zod.string().nullish().describe('Optional issue description.'),
})

export type PatchedErrorTrackingIssueWriteApi = zod.input<typeof PatchedErrorTrackingIssueWriteApi>
export type PatchedErrorTrackingIssueWriteApiOutput = zod.output<typeof PatchedErrorTrackingIssueWriteApi>

export const PatchedErrorTrackingIssueReadApi = zod
    .object({
        id: zod.uuid().optional(),
        status: zod.string().optional(),
        name: zod.string().nullish(),
        description: zod.string().nullish(),
        first_seen: zod.iso.datetime({ offset: true }).nullish(),
        assignee: zod.union([ErrorTrackingIssueAssigneeReadApi, zod.null()]).optional(),
        external_issues: zod.array(ErrorTrackingExternalReferenceResultApi).optional(),
        cohort: zod.union([ErrorTrackingIssueCohortReadApi, zod.null()]).optional(),
    })
    .describe('Read-only serializer for issue contract types returned by the facade.')

export type PatchedErrorTrackingIssueReadApi = zod.input<typeof PatchedErrorTrackingIssueReadApi>
export type PatchedErrorTrackingIssueReadApiOutput = zod.output<typeof PatchedErrorTrackingIssueReadApi>

export const ErrorTrackingIssueMergeRequestApi = zod.object({
    ids: zod.array(zod.uuid()).describe('IDs of the issues to merge into the current issue.'),
})

export type ErrorTrackingIssueMergeRequestApi = zod.input<typeof ErrorTrackingIssueMergeRequestApi>
export type ErrorTrackingIssueMergeRequestApiOutput = zod.output<typeof ErrorTrackingIssueMergeRequestApi>

export const ErrorTrackingIssueMergeResponseApi = zod.object({
    success: zod.boolean().describe('Whether the merge completed successfully.'),
})

export type ErrorTrackingIssueMergeResponseApi = zod.input<typeof ErrorTrackingIssueMergeResponseApi>
export type ErrorTrackingIssueMergeResponseApiOutput = zod.output<typeof ErrorTrackingIssueMergeResponseApi>

export const ErrorTrackingIssueSplitFingerprintApi = zod.object({
    fingerprint: zod.string().describe('Fingerprint to split into a new issue.'),
    name: zod.string().optional().describe('Optional name for the new issue created from this fingerprint.'),
    description: zod
        .string()
        .optional()
        .describe('Optional description for the new issue created from this fingerprint.'),
})

export type ErrorTrackingIssueSplitFingerprintApi = zod.input<typeof ErrorTrackingIssueSplitFingerprintApi>
export type ErrorTrackingIssueSplitFingerprintApiOutput = zod.output<typeof ErrorTrackingIssueSplitFingerprintApi>

export const ErrorTrackingIssueSplitRequestApi = zod.object({
    fingerprints: zod
        .array(ErrorTrackingIssueSplitFingerprintApi)
        .optional()
        .describe('Fingerprints to split into new issues. Each fingerprint becomes its own new issue.'),
})

export type ErrorTrackingIssueSplitRequestApi = zod.input<typeof ErrorTrackingIssueSplitRequestApi>
export type ErrorTrackingIssueSplitRequestApiOutput = zod.output<typeof ErrorTrackingIssueSplitRequestApi>

export const ErrorTrackingIssueSplitResponseApi = zod.object({
    success: zod.boolean().describe('Whether the split completed successfully.'),
    new_issue_ids: zod.array(zod.uuid()).describe('IDs of the new issues created by the split.'),
})

export type ErrorTrackingIssueSplitResponseApi = zod.input<typeof ErrorTrackingIssueSplitResponseApi>
export type ErrorTrackingIssueSplitResponseApiOutput = zod.output<typeof ErrorTrackingIssueSplitResponseApi>

export const ErrorTrackingDateRangeApi = zod.object({
    date_from: zod
        .string()
        .optional()
        .describe('Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d.'),
    date_to: zod
        .string()
        .nullish()
        .describe('End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.'),
})

export type ErrorTrackingDateRangeApi = zod.input<typeof ErrorTrackingDateRangeApi>
export type ErrorTrackingDateRangeApiOutput = zod.output<typeof ErrorTrackingDateRangeApi>

export const errorTrackingIssueQueryRequestApiFilterTestAccountsDefault = true
export const errorTrackingIssueQueryRequestApiVolumeResolutionDefault = 0
export const errorTrackingIssueQueryRequestApiVolumeResolutionMin = 0
export const errorTrackingIssueQueryRequestApiVolumeResolutionMax = 200

export const errorTrackingIssueQueryRequestApiIncludeSparklineDefault = false

export const ErrorTrackingIssueQueryRequestApi = zod.object({
    issueId: zod.uuid().describe('Error tracking issue ID.'),
    dateRange: ErrorTrackingDateRangeApi.optional().describe(
        'Date range for issue impact and latest-event metadata. Defaults to the last 7 days.'
    ),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingIssueQueryRequestApiFilterTestAccountsDefault)
        .describe('When true, exclude internal\/test account data from results. Defaults to true.'),
    volumeResolution: zod
        .number()
        .min(errorTrackingIssueQueryRequestApiVolumeResolutionMin)
        .max(errorTrackingIssueQueryRequestApiVolumeResolutionMax)
        .default(errorTrackingIssueQueryRequestApiVolumeResolutionDefault)
        .describe('Volume buckets. Maximum 200.'),
    includeSparkline: zod
        .boolean()
        .default(errorTrackingIssueQueryRequestApiIncludeSparklineDefault)
        .describe('Set true to include a compact numeric occurrence sparkline. Defaults to false.'),
})

export type ErrorTrackingIssueQueryRequestApi = zod.input<typeof ErrorTrackingIssueQueryRequestApi>
export type ErrorTrackingIssueQueryRequestApiOutput = zod.output<typeof ErrorTrackingIssueQueryRequestApi>

export const ErrorTrackingAssigneeResponseApi = zod.object({
    id: zod.union([zod.string(), zod.number(), zod.null()]).optional().describe('Assignee user ID or role UUID.'),
    type: zod.string().nullish().describe('Assignee type.'),
})

export type ErrorTrackingAssigneeResponseApi = zod.input<typeof ErrorTrackingAssigneeResponseApi>
export type ErrorTrackingAssigneeResponseApiOutput = zod.output<typeof ErrorTrackingAssigneeResponseApi>

export const ErrorTrackingVolumeBucketApi = zod.object({
    label: zod.string().describe('Bucket timestamp label.'),
    value: zod.number().nullish().describe('Occurrence count for the bucket.'),
})

export type ErrorTrackingVolumeBucketApi = zod.input<typeof ErrorTrackingVolumeBucketApi>
export type ErrorTrackingVolumeBucketApiOutput = zod.output<typeof ErrorTrackingVolumeBucketApi>

export const ErrorTrackingAggregationsApi = zod.object({
    occurrences: zod.number().optional().describe('Exception occurrence count.'),
    users: zod.number().optional().describe('Unique user count.'),
    sessions: zod.number().optional().describe('Unique session count.'),
    volumeRange: zod.array(zod.number()).optional().describe('Occurrence counts per volume bucket.'),
    volume_buckets: zod.array(ErrorTrackingVolumeBucketApi).optional().describe('Labeled volume buckets.'),
})

export type ErrorTrackingAggregationsApi = zod.input<typeof ErrorTrackingAggregationsApi>
export type ErrorTrackingAggregationsApiOutput = zod.output<typeof ErrorTrackingAggregationsApi>

export const ErrorTrackingTopFrameApi = zod.object({
    function: zod.string().optional().describe('Frame function name.'),
    source: zod.string().optional().describe('Frame source, filename, or module.'),
    line: zod.number().optional().describe('Line number.'),
    column: zod.number().optional().describe('Column number.'),
    in_app: zod.boolean().optional().describe('Whether the frame is an application frame.'),
})

export type ErrorTrackingTopFrameApi = zod.input<typeof ErrorTrackingTopFrameApi>
export type ErrorTrackingTopFrameApiOutput = zod.output<typeof ErrorTrackingTopFrameApi>

export const ErrorTrackingLatestReleaseApi = zod.object({
    version: zod.string().optional().describe('Release version.'),
    project: zod.string().optional().describe('Release project\/library.'),
    timestamp: zod.string().optional().describe('Release timestamp.'),
    commit_id: zod.string().optional().describe('Git commit ID.'),
    branch: zod.string().optional().describe('Git branch.'),
    repo_name: zod.string().optional().describe('Git repository name.'),
})

export type ErrorTrackingLatestReleaseApi = zod.input<typeof ErrorTrackingLatestReleaseApi>
export type ErrorTrackingLatestReleaseApiOutput = zod.output<typeof ErrorTrackingLatestReleaseApi>

export const ErrorTrackingImpactApi = zod.object({
    occurrences: zod.number().optional().describe('Exception occurrence count.'),
    users: zod.number().optional().describe('Unique user count.'),
    sessions: zod.number().optional().describe('Unique session count.'),
})

export type ErrorTrackingImpactApi = zod.input<typeof ErrorTrackingImpactApi>
export type ErrorTrackingImpactApiOutput = zod.output<typeof ErrorTrackingImpactApi>

export const ErrorTrackingIssueDetailApi = zod.object({
    id: zod.uuid().describe('Error tracking issue ID.'),
    name: zod.string().nullish().describe('Issue name.'),
    description: zod.string().nullish().describe('Issue description.'),
    status: zod.string().optional().describe('Issue status.'),
    first_seen: zod.iso.datetime({ offset: true }).nullish().describe('First seen timestamp.'),
    last_seen: zod.iso.datetime({ offset: true }).nullish().describe('Last seen timestamp.'),
    library: zod.string().nullish().describe('SDK\/library associated with the issue.'),
    source: zod.string().nullish().describe('Top source\/file associated with the issue.'),
    assignee: zod.union([ErrorTrackingAssigneeResponseApi, zod.null()]).optional().describe('Issue assignee.'),
    aggregations: zod.union([ErrorTrackingAggregationsApi, zod.null()]).optional().describe('Aggregate counts.'),
    function: zod.string().nullish().describe('Top function associated with the issue.'),
    top_in_app_frame: ErrorTrackingTopFrameApi.optional().describe('Top in_app application frame.'),
    latest_release: ErrorTrackingLatestReleaseApi.optional().describe('Latest release metadata.'),
    impact: ErrorTrackingImpactApi.optional().describe('Compact impact counts.'),
    sparkline: zod.array(zod.number()).optional().describe('Optional compact occurrence sparkline.'),
})

export type ErrorTrackingIssueDetailApi = zod.input<typeof ErrorTrackingIssueDetailApi>
export type ErrorTrackingIssueDetailApiOutput = zod.output<typeof ErrorTrackingIssueDetailApi>

export const PropertyItemOperatorEnumApi = zod
    .enum([
        'exact',
        'is_not',
        'icontains',
        'not_icontains',
        'starts_with',
        'not_starts_with',
        'ends_with',
        'not_ends_with',
        'regex',
        'not_regex',
        'gt',
        'lt',
        'gte',
        'lte',
        'is_set',
        'is_not_set',
        'is_date_exact',
        'is_date_after',
        'is_date_before',
        'in',
        'not_in',
    ])
    .describe(
        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `gte` - gte\n\* `lte` - lte\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `in` - in\n\* `not_in` - not_in'
    )

export type PropertyItemOperatorEnumApi = zod.input<typeof PropertyItemOperatorEnumApi>
export type PropertyItemOperatorEnumApiOutput = zod.output<typeof PropertyItemOperatorEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const PropertyFilterTypeEnumApi = zod
    .enum([
        'event',
        'event_metadata',
        'feature',
        'person',
        'person_metadata',
        'cohort',
        'element',
        'static-cohort',
        'dynamic-cohort',
        'precalculated-cohort',
        'group',
        'recording',
        'log_entry',
        'behavioral',
        'session',
        'hogql',
        'data_warehouse',
        'data_warehouse_person_property',
        'error_tracking_issue',
        'log',
        'log_attribute',
        'log_resource_attribute',
        'metric_attribute',
        'span',
        'span_attribute',
        'span_resource_attribute',
        'revenue_analytics',
        'account_custom_property',
        'flag',
        'workflow_variable',
    ])
    .describe(
        '\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `account_custom_property` - account_custom_property\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
    )

export type PropertyFilterTypeEnumApi = zod.input<typeof PropertyFilterTypeEnumApi>
export type PropertyFilterTypeEnumApiOutput = zod.output<typeof PropertyFilterTypeEnumApi>

export const propertyItemApiOperatorDefault = `exact`
export const propertyItemApiTypeDefault = `event`

export const PropertyItemApi = zod.object({
    key: zod.string().describe("Key of the property you're filtering on. For example `email` or `$current_url`"),
    value: zod
        .union([zod.string(), zod.number(), zod.boolean(), zod.array(zod.union([zod.string(), zod.number()]))])
        .describe(
            'Value of your filter. For example `test@example.com` or `https:\/\/example.com\/test\/`. Can be an array for an OR query, like `[\"test@example.com\",\"ok@example.com\"]`'
        ),
    operator: zod
        .union([PropertyItemOperatorEnumApi, BlankEnumApi, zod.null()])
        .default(propertyItemApiOperatorDefault),
    type: zod.union([PropertyFilterTypeEnumApi, BlankEnumApi]).default(propertyItemApiTypeDefault),
})

export type PropertyItemApi = zod.input<typeof PropertyItemApi>
export type PropertyItemApiOutput = zod.output<typeof PropertyItemApi>

export const OrderDirectionEnumApi = zod.enum(['ASC', 'DESC']).describe('\* `ASC` - ASC\n\* `DESC` - DESC')

export type OrderDirectionEnumApi = zod.input<typeof OrderDirectionEnumApi>
export type OrderDirectionEnumApiOutput = zod.output<typeof OrderDirectionEnumApi>

export const IncludeEnumApi = zod
    .enum([
        'exception',
        'stacktrace',
        'code_variables',
        'environment',
        'release',
        'navigation',
        'correlation',
        'diagnostics',
    ])
    .describe(
        '\* `exception` - exception\n\* `stacktrace` - stacktrace\n\* `code_variables` - code_variables\n\* `environment` - environment\n\* `release` - release\n\* `navigation` - navigation\n\* `correlation` - correlation\n\* `diagnostics` - diagnostics'
    )

export type IncludeEnumApi = zod.input<typeof IncludeEnumApi>
export type IncludeEnumApiOutput = zod.output<typeof IncludeEnumApi>

export const errorTrackingIssueEventsQueryRequestApiFilterTestAccountsDefault = true
export const errorTrackingIssueEventsQueryRequestApiSearchQueryMax = 500

export const errorTrackingIssueEventsQueryRequestApiOrderDirectionDefault = `DESC`
export const errorTrackingIssueEventsQueryRequestApiLimitDefault = 1
export const errorTrackingIssueEventsQueryRequestApiLimitMax = 20

export const errorTrackingIssueEventsQueryRequestApiOffsetDefault = 0
export const errorTrackingIssueEventsQueryRequestApiOffsetMin = 0

export const errorTrackingIssueEventsQueryRequestApiOnlyAppFramesDefault = true

export const ErrorTrackingIssueEventsQueryRequestApi = zod.object({
    issueId: zod.uuid().describe('Error tracking issue ID.'),
    dateRange: ErrorTrackingDateRangeApi.optional().describe(
        'Date range for sampled exception events. Defaults to the last 7 days.'
    ),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingIssueEventsQueryRequestApiFilterTestAccountsDefault)
        .describe('When true, exclude internal\/test account data from results. Defaults to true.'),
    filterGroup: zod
        .array(PropertyItemApi)
        .optional()
        .describe('Advanced flat AND property filters applied to sampled events. HogQL filters are rejected.'),
    searchQuery: zod
        .string()
        .max(errorTrackingIssueEventsQueryRequestApiSearchQueryMax)
        .optional()
        .describe('Search exception types, exception values, and current URL among sampled events.'),
    orderDirection: OrderDirectionEnumApi.default(
        errorTrackingIssueEventsQueryRequestApiOrderDirectionDefault
    ).describe('Timestamp sort direction. Defaults to DESC.\n\n\* `ASC` - ASC\n\* `DESC` - DESC'),
    limit: zod
        .number()
        .min(1)
        .max(errorTrackingIssueEventsQueryRequestApiLimitMax)
        .default(errorTrackingIssueEventsQueryRequestApiLimitDefault)
        .describe('Page size.'),
    offset: zod
        .number()
        .min(errorTrackingIssueEventsQueryRequestApiOffsetMin)
        .default(errorTrackingIssueEventsQueryRequestApiOffsetDefault)
        .describe('Pagination offset.'),
    include: zod
        .array(IncludeEnumApi)
        .optional()
        .describe(
            'Context groups to return. Defaults to exception, environment, navigation, and correlation. Request stacktrace for frames, code_variables for captured and SDK-masked frame variables, release for release metadata, or diagnostics for ingestion errors. code_variables implies stacktrace.'
        ),
    onlyAppFrames: zod
        .boolean()
        .default(errorTrackingIssueEventsQueryRequestApiOnlyAppFramesDefault)
        .describe('When true, include only stack frames marked in_app. Defaults to true.'),
})

export type ErrorTrackingIssueEventsQueryRequestApi = zod.input<typeof ErrorTrackingIssueEventsQueryRequestApi>
export type ErrorTrackingIssueEventsQueryRequestApiOutput = zod.output<typeof ErrorTrackingIssueEventsQueryRequestApi>

export const ErrorTrackingEventApi = zod.object({
    uuid: zod.string().optional().describe('Event UUID.'),
    distinct_id: zod.string().optional().describe('Event distinct ID.'),
    timestamp: zod.iso.datetime({ offset: true }).optional().describe('Event timestamp.'),
    properties: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Normalized sampled exception event properties.'),
})

export type ErrorTrackingEventApi = zod.input<typeof ErrorTrackingEventApi>
export type ErrorTrackingEventApiOutput = zod.output<typeof ErrorTrackingEventApi>

export const ErrorTrackingIssueEventsResponseApi = zod.object({
    results: zod.array(ErrorTrackingEventApi).describe('Sampled exception events.'),
    hasMore: zod.boolean().describe('Whether more results are available.'),
    limit: zod.number().describe('Page size.'),
    offset: zod.number().describe('Current offset.'),
    nextOffset: zod.number().optional().describe('Offset to fetch the next page when hasMore is true.'),
})

export type ErrorTrackingIssueEventsResponseApi = zod.input<typeof ErrorTrackingIssueEventsResponseApi>
export type ErrorTrackingIssueEventsResponseApiOutput = zod.output<typeof ErrorTrackingIssueEventsResponseApi>

export const ErrorTrackingIssueStatusEnumApi = zod
    .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all'])
    .describe(
        '\* `archived` - archived\n\* `active` - active\n\* `resolved` - resolved\n\* `pending_release` - pending_release\n\* `suppressed` - suppressed\n\* `all` - all'
    )

export type ErrorTrackingIssueStatusEnumApi = zod.input<typeof ErrorTrackingIssueStatusEnumApi>
export type ErrorTrackingIssueStatusEnumApiOutput = zod.output<typeof ErrorTrackingIssueStatusEnumApi>

export const ErrorTrackingAssigneeApi = zod.object({
    id: zod.union([zod.string(), zod.number(), zod.null()]).describe('User ID or role UUID to filter by.'),
    type: AssigneeTypeEnumApi.describe('Assignee target type: user or role.\n\n\* `user` - user\n\* `role` - role'),
})

export type ErrorTrackingAssigneeApi = zod.input<typeof ErrorTrackingAssigneeApi>
export type ErrorTrackingAssigneeApiOutput = zod.output<typeof ErrorTrackingAssigneeApi>

export const ErrorTrackingIssueOrderByEnumApi = zod
    .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])
    .describe(
        '\* `last_seen` - last_seen\n\* `first_seen` - first_seen\n\* `occurrences` - occurrences\n\* `users` - users\n\* `sessions` - sessions'
    )

export type ErrorTrackingIssueOrderByEnumApi = zod.input<typeof ErrorTrackingIssueOrderByEnumApi>
export type ErrorTrackingIssueOrderByEnumApiOutput = zod.output<typeof ErrorTrackingIssueOrderByEnumApi>

export const errorTrackingIssuesListQueryRequestApiStatusDefault = `active`
export const errorTrackingIssuesListQueryRequestApiFilterTestAccountsDefault = true
export const errorTrackingIssuesListQueryRequestApiSearchQueryMax = 500

export const errorTrackingIssuesListQueryRequestApiOrderByDefault = `occurrences`
export const errorTrackingIssuesListQueryRequestApiOrderDirectionDefault = `DESC`
export const errorTrackingIssuesListQueryRequestApiLimitDefault = 25
export const errorTrackingIssuesListQueryRequestApiLimitMax = 100

export const errorTrackingIssuesListQueryRequestApiOffsetDefault = 0
export const errorTrackingIssuesListQueryRequestApiOffsetMin = 0

export const errorTrackingIssuesListQueryRequestApiVolumeResolutionDefault = 0
export const errorTrackingIssuesListQueryRequestApiVolumeResolutionMin = 0
export const errorTrackingIssuesListQueryRequestApiVolumeResolutionMax = 200

export const errorTrackingIssuesListQueryRequestApiReleaseMax = 500

export const errorTrackingIssuesListQueryRequestApiUserMax = 500

export const errorTrackingIssuesListQueryRequestApiUrlMax = 1000

export const errorTrackingIssuesListQueryRequestApiFilePathMax = 1000

export const ErrorTrackingIssuesListQueryRequestApi = zod.object({
    dateRange: ErrorTrackingDateRangeApi.optional().describe(
        'Date range for issue aggregates. Defaults to the last 7 days.'
    ),
    status: ErrorTrackingIssueStatusEnumApi.default(errorTrackingIssuesListQueryRequestApiStatusDefault).describe(
        'Filter by issue status. Defaults to active.\n\n\* `archived` - archived\n\* `active` - active\n\* `resolved` - resolved\n\* `pending_release` - pending_release\n\* `suppressed` - suppressed\n\* `all` - all'
    ),
    assignee: zod
        .union([ErrorTrackingAssigneeApi, zod.null()])
        .optional()
        .describe('Filter by issue assignee. Omit to include all assignees.'),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingIssuesListQueryRequestApiFilterTestAccountsDefault)
        .describe('When true, exclude internal\/test account data from results. Defaults to true.'),
    searchQuery: zod
        .string()
        .max(errorTrackingIssuesListQueryRequestApiSearchQueryMax)
        .optional()
        .describe('Free-text search across exception types, values, stack frames, and email fields.'),
    filterGroup: zod
        .array(PropertyItemApi)
        .optional()
        .describe(
            'Advanced flat AND property filters. Prefer typed shortcut fields when they fit. HogQL filters are rejected.'
        ),
    orderBy: ErrorTrackingIssueOrderByEnumApi.default(errorTrackingIssuesListQueryRequestApiOrderByDefault).describe(
        'Field used to sort issues. Defaults to occurrences.\n\n\* `last_seen` - last_seen\n\* `first_seen` - first_seen\n\* `occurrences` - occurrences\n\* `users` - users\n\* `sessions` - sessions'
    ),
    orderDirection: OrderDirectionEnumApi.default(errorTrackingIssuesListQueryRequestApiOrderDirectionDefault).describe(
        'Sort direction. Defaults to DESC.\n\n\* `ASC` - ASC\n\* `DESC` - DESC'
    ),
    limit: zod
        .number()
        .min(1)
        .max(errorTrackingIssuesListQueryRequestApiLimitMax)
        .default(errorTrackingIssuesListQueryRequestApiLimitDefault)
        .describe('Page size.'),
    offset: zod
        .number()
        .min(errorTrackingIssuesListQueryRequestApiOffsetMin)
        .default(errorTrackingIssuesListQueryRequestApiOffsetDefault)
        .describe('Pagination offset.'),
    volumeResolution: zod
        .number()
        .min(errorTrackingIssuesListQueryRequestApiVolumeResolutionMin)
        .max(errorTrackingIssuesListQueryRequestApiVolumeResolutionMax)
        .default(errorTrackingIssuesListQueryRequestApiVolumeResolutionDefault)
        .describe('Number of volume buckets. Defaults to 0 for compact aggregate counts.'),
    library: zod
        .union([zod.string(), zod.array(zod.string()).min(1)])
        .optional()
        .describe('Filter by SDK\/library value from event $lib, for example posthog-js.'),
    release: zod
        .string()
        .max(errorTrackingIssuesListQueryRequestApiReleaseMax)
        .optional()
        .describe('Filter by exact release ID, version, or git commit ID captured in $exception_releases.'),
    fingerprint: zod
        .union([zod.string(), zod.array(zod.string()).min(1)])
        .optional()
        .describe('Filter by exact exception fingerprint hash, not fuzzy search.'),
    user: zod
        .string()
        .max(errorTrackingIssuesListQueryRequestApiUserMax)
        .optional()
        .describe('Search user\/email text.'),
    personId: zod.uuid().optional().describe('Filter by exact PostHog person UUID.'),
    url: zod
        .string()
        .max(errorTrackingIssuesListQueryRequestApiUrlMax)
        .optional()
        .describe('Filter by current URL substring.'),
    filePath: zod
        .string()
        .max(errorTrackingIssuesListQueryRequestApiFilePathMax)
        .optional()
        .describe('Search stack-frame source\/file path text.'),
})

export type ErrorTrackingIssuesListQueryRequestApi = zod.input<typeof ErrorTrackingIssuesListQueryRequestApi>
export type ErrorTrackingIssuesListQueryRequestApiOutput = zod.output<typeof ErrorTrackingIssuesListQueryRequestApi>

export const ErrorTrackingIssueListItemApi = zod.object({
    id: zod.uuid().describe('Error tracking issue ID.'),
    name: zod.string().nullish().describe('Issue name.'),
    description: zod.string().nullish().describe('Issue description.'),
    status: zod.string().optional().describe('Issue status.'),
    first_seen: zod.iso.datetime({ offset: true }).nullish().describe('First seen timestamp.'),
    last_seen: zod.iso.datetime({ offset: true }).nullish().describe('Last seen timestamp.'),
    library: zod.string().nullish().describe('SDK\/library associated with the issue.'),
    source: zod.string().nullish().describe('Top source\/file associated with the issue.'),
    assignee: zod.union([ErrorTrackingAssigneeResponseApi, zod.null()]).optional().describe('Issue assignee.'),
    aggregations: zod.union([ErrorTrackingAggregationsApi, zod.null()]).optional().describe('Aggregate counts.'),
})

export type ErrorTrackingIssueListItemApi = zod.input<typeof ErrorTrackingIssueListItemApi>
export type ErrorTrackingIssueListItemApiOutput = zod.output<typeof ErrorTrackingIssueListItemApi>

export const ErrorTrackingIssuesListResponseApi = zod.object({
    results: zod.array(ErrorTrackingIssueListItemApi).describe('Issue rows.'),
    hasMore: zod.boolean().describe('Whether more results are available.'),
    limit: zod.number().describe('Page size.'),
    offset: zod.number().describe('Current offset.'),
    nextOffset: zod.number().optional().describe('Offset to fetch the next page when hasMore is true.'),
})

export type ErrorTrackingIssuesListResponseApi = zod.input<typeof ErrorTrackingIssuesListResponseApi>
export type ErrorTrackingIssuesListResponseApiOutput = zod.output<typeof ErrorTrackingIssuesListResponseApi>

export const ErrorTrackingRecommendationApi = zod.object({
    id: zod.uuid().describe('Recommendation UUID.'),
    type: zod.string().describe("Recommendation type identifier (e.g. 'alerts')."),
    meta: zod.unknown().describe('Recommendation payload, shape depends on type.'),
    completed: zod.boolean().describe("Whether the recommendation's recommended action has been satisfied."),
    status: zod.string().describe("'ready' if meta is fresh, 'computing' if a refresh is in progress."),
    computed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp meta was last successfully computed.'),
    dismissed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp the user dismissed this recommendation, if any.'),
    created_at: zod.iso.datetime({ offset: true }).describe('Timestamp the recommendation row was first created.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('Timestamp the recommendation row was last updated.'),
})

export type ErrorTrackingRecommendationApi = zod.input<typeof ErrorTrackingRecommendationApi>
export type ErrorTrackingRecommendationApiOutput = zod.output<typeof ErrorTrackingRecommendationApi>

export const PaginatedErrorTrackingRecommendationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingRecommendationApi),
})

export type PaginatedErrorTrackingRecommendationListApi = zod.input<typeof PaginatedErrorTrackingRecommendationListApi>
export type PaginatedErrorTrackingRecommendationListApiOutput = zod.output<
    typeof PaginatedErrorTrackingRecommendationListApi
>

export const ErrorTrackingReleaseApi = zod.object({
    id: zod.uuid(),
    hash_id: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    metadata: zod.record(zod.string(), zod.unknown()).nullable(),
    version: zod.string(),
    project: zod.string(),
})

export type ErrorTrackingReleaseApi = zod.input<typeof ErrorTrackingReleaseApi>
export type ErrorTrackingReleaseApiOutput = zod.output<typeof ErrorTrackingReleaseApi>

export const PaginatedErrorTrackingReleaseListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingReleaseApi),
})

export type PaginatedErrorTrackingReleaseListApi = zod.input<typeof PaginatedErrorTrackingReleaseListApi>
export type PaginatedErrorTrackingReleaseListApiOutput = zod.output<typeof PaginatedErrorTrackingReleaseListApi>

export const errorTrackingReleaseCreateRequestApiHashIdMax = 128

export const ErrorTrackingReleaseCreateRequestApi = zod.object({
    version: zod.string().describe('Human-readable release version, e.g. a semver string or build number.'),
    project: zod.string().describe('Identifier of the project this release belongs to.'),
    hash_id: zod
        .string()
        .max(errorTrackingReleaseCreateRequestApiHashIdMax)
        .nullish()
        .describe('Optional client-supplied release hash (e.g. a git commit SHA). Generated server-side when omitted.'),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Optional free-form metadata object stored alongside the release.'),
})

export type ErrorTrackingReleaseCreateRequestApi = zod.input<typeof ErrorTrackingReleaseCreateRequestApi>
export type ErrorTrackingReleaseCreateRequestApiOutput = zod.output<typeof ErrorTrackingReleaseCreateRequestApi>

export const errorTrackingReleaseUpdateRequestApiHashIdMax = 128

export const ErrorTrackingReleaseUpdateRequestApi = zod.object({
    version: zod.string().nullish().describe('Human-readable release version. Omit to preserve the current value.'),
    project: zod.string().nullish().describe('Project identifier. Omit to preserve the current value.'),
    hash_id: zod
        .string()
        .max(errorTrackingReleaseUpdateRequestApiHashIdMax)
        .nullish()
        .describe('Release hash (e.g. a git commit SHA). Omit to preserve the current value.'),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Free-form metadata object. Omit to preserve the current value.'),
})

export type ErrorTrackingReleaseUpdateRequestApi = zod.input<typeof ErrorTrackingReleaseUpdateRequestApi>
export type ErrorTrackingReleaseUpdateRequestApiOutput = zod.output<typeof ErrorTrackingReleaseUpdateRequestApi>

export const patchedErrorTrackingReleaseUpdateRequestApiHashIdMax = 128

export const PatchedErrorTrackingReleaseUpdateRequestApi = zod.object({
    version: zod.string().nullish().describe('Human-readable release version. Omit to preserve the current value.'),
    project: zod.string().nullish().describe('Project identifier. Omit to preserve the current value.'),
    hash_id: zod
        .string()
        .max(patchedErrorTrackingReleaseUpdateRequestApiHashIdMax)
        .nullish()
        .describe('Release hash (e.g. a git commit SHA). Omit to preserve the current value.'),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Free-form metadata object. Omit to preserve the current value.'),
})

export type PatchedErrorTrackingReleaseUpdateRequestApi = zod.input<typeof PatchedErrorTrackingReleaseUpdateRequestApi>
export type PatchedErrorTrackingReleaseUpdateRequestApiOutput = zod.output<
    typeof PatchedErrorTrackingReleaseUpdateRequestApi
>

export const ErrorTrackingSettingsApi = zod.object({
    project_rate_limit_value: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Maximum number of exception events ingested per bucket for the entire project. Null removes the limit.'
        ),
    project_rate_limit_bucket_size_minutes: zod
        .number()
        .min(1)
        .nullish()
        .describe('Bucket window over which the project-wide rate limit applies, in minutes.'),
    per_issue_rate_limit_value: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Maximum number of exception events ingested per bucket for each individual issue. Null removes the limit.'
        ),
    per_issue_rate_limit_bucket_size_minutes: zod
        .number()
        .min(1)
        .nullish()
        .describe('Bucket window over which the per-issue rate limit applies, in minutes.'),
})

export type ErrorTrackingSettingsApi = zod.input<typeof ErrorTrackingSettingsApi>
export type ErrorTrackingSettingsApiOutput = zod.output<typeof ErrorTrackingSettingsApi>

export const PatchedErrorTrackingSettingsApi = zod.object({
    project_rate_limit_value: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Maximum number of exception events ingested per bucket for the entire project. Null removes the limit.'
        ),
    project_rate_limit_bucket_size_minutes: zod
        .number()
        .min(1)
        .nullish()
        .describe('Bucket window over which the project-wide rate limit applies, in minutes.'),
    per_issue_rate_limit_value: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Maximum number of exception events ingested per bucket for each individual issue. Null removes the limit.'
        ),
    per_issue_rate_limit_bucket_size_minutes: zod
        .number()
        .min(1)
        .nullish()
        .describe('Bucket window over which the per-issue rate limit applies, in minutes.'),
})

export type PatchedErrorTrackingSettingsApi = zod.input<typeof PatchedErrorTrackingSettingsApi>
export type PatchedErrorTrackingSettingsApiOutput = zod.output<typeof PatchedErrorTrackingSettingsApi>

export const ErrorTrackingSpikeDetectionConfigApi = zod.object({
    snooze_duration_minutes: zod
        .number()
        .min(1)
        .describe('Time to wait before alerting again for the same issue after a spike is detected.'),
    multiplier: zod
        .number()
        .min(1)
        .describe('The factor by which the current exception count must exceed the baseline to be considered a spike.'),
    threshold: zod
        .number()
        .min(1)
        .describe('The minimum number of exceptions required in a 5-minute window before a spike can be detected.'),
})

export type ErrorTrackingSpikeDetectionConfigApi = zod.input<typeof ErrorTrackingSpikeDetectionConfigApi>
export type ErrorTrackingSpikeDetectionConfigApiOutput = zod.output<typeof ErrorTrackingSpikeDetectionConfigApi>

export const PatchedErrorTrackingSpikeDetectionConfigApi = zod.object({
    snooze_duration_minutes: zod
        .number()
        .min(1)
        .optional()
        .describe('Time to wait before alerting again for the same issue after a spike is detected.'),
    multiplier: zod
        .number()
        .min(1)
        .optional()
        .describe('The factor by which the current exception count must exceed the baseline to be considered a spike.'),
    threshold: zod
        .number()
        .min(1)
        .optional()
        .describe('The minimum number of exceptions required in a 5-minute window before a spike can be detected.'),
})

export type PatchedErrorTrackingSpikeDetectionConfigApi = zod.input<typeof PatchedErrorTrackingSpikeDetectionConfigApi>
export type PatchedErrorTrackingSpikeDetectionConfigApiOutput = zod.output<
    typeof PatchedErrorTrackingSpikeDetectionConfigApi
>

export const ErrorTrackingSpikeEventIssueApi = zod.object({
    id: zod.uuid(),
    name: zod.string().nullable(),
    description: zod.string().nullable(),
})

export type ErrorTrackingSpikeEventIssueApi = zod.input<typeof ErrorTrackingSpikeEventIssueApi>
export type ErrorTrackingSpikeEventIssueApiOutput = zod.output<typeof ErrorTrackingSpikeEventIssueApi>

export const ErrorTrackingSpikeEventApi = zod.object({
    id: zod.uuid(),
    issue: ErrorTrackingSpikeEventIssueApi,
    detected_at: zod.iso.datetime({ offset: true }),
    computed_baseline: zod.number(),
    current_bucket_value: zod.number(),
})

export type ErrorTrackingSpikeEventApi = zod.input<typeof ErrorTrackingSpikeEventApi>
export type ErrorTrackingSpikeEventApiOutput = zod.output<typeof ErrorTrackingSpikeEventApi>

export const PaginatedErrorTrackingSpikeEventListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingSpikeEventApi),
})

export type PaginatedErrorTrackingSpikeEventListApi = zod.input<typeof PaginatedErrorTrackingSpikeEventListApi>
export type PaginatedErrorTrackingSpikeEventListApiOutput = zod.output<typeof PaginatedErrorTrackingSpikeEventListApi>

export const ErrorTrackingStackFrameApi = zod.object({
    id: zod.uuid(),
    raw_id: zod.string(),
    created_at: zod.iso.datetime({ offset: true }),
    contents: zod.record(zod.string(), zod.unknown()),
    resolved: zod.boolean(),
    context: zod.record(zod.string(), zod.unknown()).nullable(),
    symbol_set_ref: zod.string().nullable(),
    release: zod.union([ErrorTrackingReleaseApi, zod.null()]),
})

export type ErrorTrackingStackFrameApi = zod.input<typeof ErrorTrackingStackFrameApi>
export type ErrorTrackingStackFrameApiOutput = zod.output<typeof ErrorTrackingStackFrameApi>

export const PaginatedErrorTrackingStackFrameListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingStackFrameApi),
})

export type PaginatedErrorTrackingStackFrameListApi = zod.input<typeof PaginatedErrorTrackingStackFrameListApi>
export type PaginatedErrorTrackingStackFrameListApiOutput = zod.output<typeof PaginatedErrorTrackingStackFrameListApi>

export const ErrorTrackingStackFrameBatchGetRequestApi = zod.object({
    raw_ids: zod.array(zod.string()).describe("Raw frame IDs in 'hash\/part' format to resolve in a single request."),
    symbol_set: zod
        .string()
        .nullish()
        .describe('Optional symbol set reference to scope the lookup to a single symbol set.'),
})

export type ErrorTrackingStackFrameBatchGetRequestApi = zod.input<typeof ErrorTrackingStackFrameBatchGetRequestApi>
export type ErrorTrackingStackFrameBatchGetRequestApiOutput = zod.output<
    typeof ErrorTrackingStackFrameBatchGetRequestApi
>

export const ErrorTrackingStackFrameBatchGetResponseApi = zod.object({
    results: zod.array(ErrorTrackingStackFrameApi).describe('Resolved stack frames for the requested raw IDs.'),
})

export type ErrorTrackingStackFrameBatchGetResponseApi = zod.input<typeof ErrorTrackingStackFrameBatchGetResponseApi>
export type ErrorTrackingStackFrameBatchGetResponseApiOutput = zod.output<
    typeof ErrorTrackingStackFrameBatchGetResponseApi
>

export const ErrorTrackingSuppressionRuleApi = zod.object({
    id: zod.uuid(),
    filters: zod.unknown(),
    order_key: zod.number(),
    disabled_data: zod.unknown(),
    sampling_rate: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type ErrorTrackingSuppressionRuleApi = zod.input<typeof ErrorTrackingSuppressionRuleApi>
export type ErrorTrackingSuppressionRuleApiOutput = zod.output<typeof ErrorTrackingSuppressionRuleApi>

export const PaginatedErrorTrackingSuppressionRuleListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingSuppressionRuleApi),
})

export type PaginatedErrorTrackingSuppressionRuleListApi = zod.input<
    typeof PaginatedErrorTrackingSuppressionRuleListApi
>
export type PaginatedErrorTrackingSuppressionRuleListApiOutput = zod.output<
    typeof PaginatedErrorTrackingSuppressionRuleListApi
>

export const errorTrackingSuppressionRuleCreateRequestApiSamplingRateDefault = 1
export const errorTrackingSuppressionRuleCreateRequestApiSamplingRateMin = 0
export const errorTrackingSuppressionRuleCreateRequestApiSamplingRateMax = 1

export const ErrorTrackingSuppressionRuleCreateRequestApi = zod.object({
    filters: PropertyGroupFilterValueApi.optional().describe(
        'Optional property-group filters that define which incoming error events should be suppressed. Omit this field or provide an empty `values` array to create a match-all suppression rule.'
    ),
    sampling_rate: zod
        .number()
        .min(errorTrackingSuppressionRuleCreateRequestApiSamplingRateMin)
        .max(errorTrackingSuppressionRuleCreateRequestApiSamplingRateMax)
        .default(errorTrackingSuppressionRuleCreateRequestApiSamplingRateDefault)
        .describe(
            'Probability that a matching event is dropped. `1.0` drops every match (default); `0.0` drops none; `0.5` drops half. Higher values suppress more.'
        ),
})

export type ErrorTrackingSuppressionRuleCreateRequestApi = zod.input<
    typeof ErrorTrackingSuppressionRuleCreateRequestApi
>
export type ErrorTrackingSuppressionRuleCreateRequestApiOutput = zod.output<
    typeof ErrorTrackingSuppressionRuleCreateRequestApi
>

export const errorTrackingSuppressionRuleUpdateRequestApiSamplingRateMin = 0
export const errorTrackingSuppressionRuleUpdateRequestApiSamplingRateMax = 1

export const ErrorTrackingSuppressionRuleUpdateRequestApi = zod.object({
    filters: PropertyGroupFilterValueApi.optional().describe(
        'Property-group filters that define which incoming error events should be suppressed. Provide an empty `values` array to convert the rule into a match-all suppression. Omit to preserve the existing filters.'
    ),
    sampling_rate: zod
        .number()
        .min(errorTrackingSuppressionRuleUpdateRequestApiSamplingRateMin)
        .max(errorTrackingSuppressionRuleUpdateRequestApiSamplingRateMax)
        .optional()
        .describe(
            'Probability that a matching event is dropped. `1.0` drops every match; `0.0` drops none; `0.5` drops half. Higher values suppress more. Omit to preserve the existing rate.'
        ),
})

export type ErrorTrackingSuppressionRuleUpdateRequestApi = zod.input<
    typeof ErrorTrackingSuppressionRuleUpdateRequestApi
>
export type ErrorTrackingSuppressionRuleUpdateRequestApiOutput = zod.output<
    typeof ErrorTrackingSuppressionRuleUpdateRequestApi
>

export const patchedErrorTrackingSuppressionRuleUpdateRequestApiSamplingRateMin = 0
export const patchedErrorTrackingSuppressionRuleUpdateRequestApiSamplingRateMax = 1

export const PatchedErrorTrackingSuppressionRuleUpdateRequestApi = zod.object({
    filters: PropertyGroupFilterValueApi.optional().describe(
        'Property-group filters that define which incoming error events should be suppressed. Provide an empty `values` array to convert the rule into a match-all suppression. Omit to preserve the existing filters.'
    ),
    sampling_rate: zod
        .number()
        .min(patchedErrorTrackingSuppressionRuleUpdateRequestApiSamplingRateMin)
        .max(patchedErrorTrackingSuppressionRuleUpdateRequestApiSamplingRateMax)
        .optional()
        .describe(
            'Probability that a matching event is dropped. `1.0` drops every match; `0.0` drops none; `0.5` drops half. Higher values suppress more. Omit to preserve the existing rate.'
        ),
})

export type PatchedErrorTrackingSuppressionRuleUpdateRequestApi = zod.input<
    typeof PatchedErrorTrackingSuppressionRuleUpdateRequestApi
>
export type PatchedErrorTrackingSuppressionRuleUpdateRequestApiOutput = zod.output<
    typeof PatchedErrorTrackingSuppressionRuleUpdateRequestApi
>

export const PatchedErrorTrackingSuppressionRuleApi = zod.object({
    id: zod.uuid().optional(),
    filters: zod.unknown().optional(),
    order_key: zod.number().optional(),
    disabled_data: zod.unknown().optional(),
    sampling_rate: zod.number().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedErrorTrackingSuppressionRuleApi = zod.input<typeof PatchedErrorTrackingSuppressionRuleApi>
export type PatchedErrorTrackingSuppressionRuleApiOutput = zod.output<typeof PatchedErrorTrackingSuppressionRuleApi>

export const ErrorTrackingSymbolSetApi = zod.object({
    id: zod.uuid(),
    ref: zod.string(),
    team_id: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    last_used: zod.iso.datetime({ offset: true }).nullable(),
    failure_reason: zod.string().nullable(),
    has_uploaded_file: zod.boolean(),
    release: zod.union([ErrorTrackingReleaseApi, zod.null()]),
})

export type ErrorTrackingSymbolSetApi = zod.input<typeof ErrorTrackingSymbolSetApi>
export type ErrorTrackingSymbolSetApiOutput = zod.output<typeof ErrorTrackingSymbolSetApi>

export const PaginatedErrorTrackingSymbolSetListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ErrorTrackingSymbolSetApi),
})

export type PaginatedErrorTrackingSymbolSetListApi = zod.input<typeof PaginatedErrorTrackingSymbolSetListApi>
export type PaginatedErrorTrackingSymbolSetListApiOutput = zod.output<typeof PaginatedErrorTrackingSymbolSetListApi>

export const _SymbolSetDownloadResponseApi = zod.object({
    url: zod.url().describe('Presigned URL to download the source map file. Use immediately; expires after one hour.'),
})

export type _SymbolSetDownloadResponseApi = zod.input<typeof _SymbolSetDownloadResponseApi>
export type _SymbolSetDownloadResponseApiOutput = zod.output<typeof _SymbolSetDownloadResponseApi>

export const ErrorTrackingSymbolSetFinishUploadApi = zod.object({
    content_hash: zod.string().describe('Hash of the uploaded symbol set content.'),
})

export type ErrorTrackingSymbolSetFinishUploadApi = zod.input<typeof ErrorTrackingSymbolSetFinishUploadApi>
export type ErrorTrackingSymbolSetFinishUploadApiOutput = zod.output<typeof ErrorTrackingSymbolSetFinishUploadApi>

export const ErrorTrackingSymbolSetBulkDeleteApi = zod.object({
    ids: zod.array(zod.uuid()).describe('Symbol set IDs to delete.'),
})

export type ErrorTrackingSymbolSetBulkDeleteApi = zod.input<typeof ErrorTrackingSymbolSetBulkDeleteApi>
export type ErrorTrackingSymbolSetBulkDeleteApiOutput = zod.output<typeof ErrorTrackingSymbolSetBulkDeleteApi>

export const ErrorTrackingSymbolSetBulkFinishUploadApi = zod.object({
    content_hashes: zod.record(zod.string(), zod.string()).describe('Map of symbol set ID to uploaded content hash.'),
})

export type ErrorTrackingSymbolSetBulkFinishUploadApi = zod.input<typeof ErrorTrackingSymbolSetBulkFinishUploadApi>
export type ErrorTrackingSymbolSetBulkFinishUploadApiOutput = zod.output<
    typeof ErrorTrackingSymbolSetBulkFinishUploadApi
>

export const ErrorTrackingSymbolSetUploadApi = zod.object({
    chunk_id: zod.string().describe('Symbol set reference to upload.'),
    release_id: zod.string().nullish().describe('Optional error tracking release ID associated with this symbol set.'),
    content_hash: zod
        .string()
        .nullish()
        .describe('Optional hash of the symbol set content, used to skip unchanged uploads.'),
})

export type ErrorTrackingSymbolSetUploadApi = zod.input<typeof ErrorTrackingSymbolSetUploadApi>
export type ErrorTrackingSymbolSetUploadApiOutput = zod.output<typeof ErrorTrackingSymbolSetUploadApi>

export const errorTrackingSymbolSetBulkStartUploadApiForceDefault = false
export const errorTrackingSymbolSetBulkStartUploadApiSkipOnConflictDefault = false

export const ErrorTrackingSymbolSetBulkStartUploadApi = zod.object({
    chunk_ids: zod
        .array(zod.string())
        .optional()
        .describe('Legacy list of symbol set references to upload, all associated with `release_id`.'),
    release_id: zod.string().nullish().describe('Optional error tracking release ID used with `chunk_ids`.'),
    symbol_sets: zod
        .array(ErrorTrackingSymbolSetUploadApi)
        .optional()
        .describe('Symbol sets to upload with per-symbol release IDs and content hashes.'),
    force: zod
        .boolean()
        .default(errorTrackingSymbolSetBulkStartUploadApiForceDefault)
        .describe('Whether to overwrite uploaded symbol sets whose content hash changed.'),
    skip_on_conflict: zod
        .boolean()
        .default(errorTrackingSymbolSetBulkStartUploadApiSkipOnConflictDefault)
        .describe('Whether to skip uploaded symbol sets whose content hash changed instead of failing.'),
})

export type ErrorTrackingSymbolSetBulkStartUploadApi = zod.input<typeof ErrorTrackingSymbolSetBulkStartUploadApi>
export type ErrorTrackingSymbolSetBulkStartUploadApiOutput = zod.output<typeof ErrorTrackingSymbolSetBulkStartUploadApi>

export const FilterLogicalOperatorApi = zod.enum(['AND', 'OR'])

export type FilterLogicalOperatorApi = zod.input<typeof FilterLogicalOperatorApi>
export type FilterLogicalOperatorApiOutput = zod.output<typeof FilterLogicalOperatorApi>

export const PropertyOperatorApi = zod.enum([
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'starts_with',
    'not_starts_with',
    'ends_with',
    'not_ends_with',
    'regex',
    'not_regex',
    'gt',
    'gte',
    'lt',
    'lte',
    'is_set',
    'is_not_set',
    'is_date_exact',
    'is_date_before',
    'is_date_after',
    'between',
    'not_between',
    'min',
    'max',
    'in',
    'not_in',
    'is_cleaned_path_exact',
    'flag_evaluates_to',
    'semver_eq',
    'semver_neq',
    'semver_gt',
    'semver_gte',
    'semver_lt',
    'semver_lte',
    'semver_tilde',
    'semver_caret',
    'semver_wildcard',
    'icontains_multi',
    'not_icontains_multi',
])

export type PropertyOperatorApi = zod.input<typeof PropertyOperatorApi>
export type PropertyOperatorApiOutput = zod.output<typeof PropertyOperatorApi>

export const eventPropertyFilterApiOperatorDefault = `exact`
export const eventPropertyFilterApiTypeDefault = `event`

export const EventPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod.union([PropertyOperatorApi, zod.null()]).default(eventPropertyFilterApiOperatorDefault),
    type: zod.literal('event').default(eventPropertyFilterApiTypeDefault).describe('Event properties'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type EventPropertyFilterApi = zod.input<typeof EventPropertyFilterApi>
export type EventPropertyFilterApiOutput = zod.output<typeof EventPropertyFilterApi>

export const personPropertyFilterApiTypeDefault = `person`

export const PersonPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('person').default(personPropertyFilterApiTypeDefault).describe('Person properties'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type PersonPropertyFilterApi = zod.input<typeof PersonPropertyFilterApi>
export type PersonPropertyFilterApiOutput = zod.output<typeof PersonPropertyFilterApi>

export const personMetadataPropertyFilterApiTypeDefault = `person_metadata`

export const PersonMetadataPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('person_metadata')
        .default(personMetadataPropertyFilterApiTypeDefault)
        .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type PersonMetadataPropertyFilterApi = zod.input<typeof PersonMetadataPropertyFilterApi>
export type PersonMetadataPropertyFilterApiOutput = zod.output<typeof PersonMetadataPropertyFilterApi>

export const Key10Api = zod.enum(['tag_name', 'text', 'href', 'selector'])

export type Key10Api = zod.input<typeof Key10Api>
export type Key10ApiOutput = zod.output<typeof Key10Api>

export const elementPropertyFilterApiTypeDefault = `element`

export const ElementPropertyFilterApi = zod.object({
    key: Key10Api,
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('element').default(elementPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ElementPropertyFilterApi = zod.input<typeof ElementPropertyFilterApi>
export type ElementPropertyFilterApiOutput = zod.output<typeof ElementPropertyFilterApi>

export const eventMetadataPropertyFilterApiTypeDefault = `event_metadata`

export const EventMetadataPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('event_metadata').default(eventMetadataPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type EventMetadataPropertyFilterApi = zod.input<typeof EventMetadataPropertyFilterApi>
export type EventMetadataPropertyFilterApiOutput = zod.output<typeof EventMetadataPropertyFilterApi>

export const sessionPropertyFilterApiTypeDefault = `session`

export const SessionPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('session').default(sessionPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type SessionPropertyFilterApi = zod.input<typeof SessionPropertyFilterApi>
export type SessionPropertyFilterApiOutput = zod.output<typeof SessionPropertyFilterApi>

export const cohortPropertyFilterApiKeyDefault = `id`
export const cohortPropertyFilterApiOperatorDefault = `in`
export const cohortPropertyFilterApiTypeDefault = `cohort`

export const CohortPropertyFilterApi = zod.object({
    cohort_name: zod.union([zod.string(), zod.null()]).optional(),
    key: zod.literal('id').default(cohortPropertyFilterApiKeyDefault),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod.union([PropertyOperatorApi, zod.null()]).default(cohortPropertyFilterApiOperatorDefault),
    type: zod.literal('cohort').default(cohortPropertyFilterApiTypeDefault),
    value: zod.number(),
})

export type CohortPropertyFilterApi = zod.input<typeof CohortPropertyFilterApi>
export type CohortPropertyFilterApiOutput = zod.output<typeof CohortPropertyFilterApi>

export const DurationTypeApi = zod.enum(['duration', 'active_seconds', 'inactive_seconds'])

export type DurationTypeApi = zod.input<typeof DurationTypeApi>
export type DurationTypeApiOutput = zod.output<typeof DurationTypeApi>

export const recordingPropertyFilterApiTypeDefault = `recording`

export const RecordingPropertyFilterApi = zod.object({
    key: zod.union([DurationTypeApi, zod.string()]),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('recording').default(recordingPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type RecordingPropertyFilterApi = zod.input<typeof RecordingPropertyFilterApi>
export type RecordingPropertyFilterApiOutput = zod.output<typeof RecordingPropertyFilterApi>

export const logEntryPropertyFilterApiTypeDefault = `log_entry`

export const LogEntryPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('log_entry').default(logEntryPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type LogEntryPropertyFilterApi = zod.input<typeof LogEntryPropertyFilterApi>
export type LogEntryPropertyFilterApiOutput = zod.output<typeof LogEntryPropertyFilterApi>

export const groupPropertyFilterApiTypeDefault = `group`

export const GroupPropertyFilterApi = zod.object({
    group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
    group_type_index: zod.union([zod.number(), zod.null()]).optional(),
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('group').default(groupPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type GroupPropertyFilterApi = zod.input<typeof GroupPropertyFilterApi>
export type GroupPropertyFilterApiOutput = zod.output<typeof GroupPropertyFilterApi>

export const featurePropertyFilterApiTypeDefault = `feature`

export const FeaturePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('feature')
        .default(featurePropertyFilterApiTypeDefault)
        .describe('Event property with \"$feature\/\" prepended'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type FeaturePropertyFilterApi = zod.input<typeof FeaturePropertyFilterApi>
export type FeaturePropertyFilterApiOutput = zod.output<typeof FeaturePropertyFilterApi>

export const flagPropertyFilterApiOperatorDefault = `flag_evaluates_to`
export const flagPropertyFilterApiTypeDefault = `flag`

export const FlagPropertyFilterApi = zod.object({
    key: zod.string().describe('The key should be the flag ID'),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod
        .literal('flag_evaluates_to')
        .default(flagPropertyFilterApiOperatorDefault)
        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
    type: zod.literal('flag').default(flagPropertyFilterApiTypeDefault).describe('Feature flag dependency'),
    value: zod.union([zod.boolean(), zod.string()]).describe('The value can be true, false, or a variant name'),
})

export type FlagPropertyFilterApi = zod.input<typeof FlagPropertyFilterApi>
export type FlagPropertyFilterApiOutput = zod.output<typeof FlagPropertyFilterApi>

export const hogQLPropertyFilterApiTypeDefault = `hogql`

export const HogQLPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    type: zod.literal('hogql').default(hogQLPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type HogQLPropertyFilterApi = zod.input<typeof HogQLPropertyFilterApi>
export type HogQLPropertyFilterApiOutput = zod.output<typeof HogQLPropertyFilterApi>

export const emptyPropertyFilterApiTypeDefault = `empty`

export const EmptyPropertyFilterApi = zod.object({
    type: zod.literal('empty').default(emptyPropertyFilterApiTypeDefault),
})

export type EmptyPropertyFilterApi = zod.input<typeof EmptyPropertyFilterApi>
export type EmptyPropertyFilterApiOutput = zod.output<typeof EmptyPropertyFilterApi>

export const dataWarehousePropertyFilterApiTypeDefault = `data_warehouse`

export const DataWarehousePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('data_warehouse').default(dataWarehousePropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type DataWarehousePropertyFilterApi = zod.input<typeof DataWarehousePropertyFilterApi>
export type DataWarehousePropertyFilterApiOutput = zod.output<typeof DataWarehousePropertyFilterApi>

export const dataWarehousePersonPropertyFilterApiTypeDefault = `data_warehouse_person_property`

export const DataWarehousePersonPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('data_warehouse_person_property').default(dataWarehousePersonPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type DataWarehousePersonPropertyFilterApi = zod.input<typeof DataWarehousePersonPropertyFilterApi>
export type DataWarehousePersonPropertyFilterApiOutput = zod.output<typeof DataWarehousePersonPropertyFilterApi>

export const errorTrackingIssueFilterApiTypeDefault = `error_tracking_issue`

export const ErrorTrackingIssueFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('error_tracking_issue').default(errorTrackingIssueFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ErrorTrackingIssueFilterApi = zod.input<typeof ErrorTrackingIssueFilterApi>
export type ErrorTrackingIssueFilterApiOutput = zod.output<typeof ErrorTrackingIssueFilterApi>

export const LogPropertyFilterTypeApi = zod.enum(['log', 'log_attribute', 'log_resource_attribute'])

export type LogPropertyFilterTypeApi = zod.input<typeof LogPropertyFilterTypeApi>
export type LogPropertyFilterTypeApiOutput = zod.output<typeof LogPropertyFilterTypeApi>

export const LogPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: LogPropertyFilterTypeApi,
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type LogPropertyFilterApi = zod.input<typeof LogPropertyFilterApi>
export type LogPropertyFilterApiOutput = zod.output<typeof LogPropertyFilterApi>

export const metricPropertyFilterApiTypeDefault = `metric_attribute`

export const MetricPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('metric_attribute').default(metricPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type MetricPropertyFilterApi = zod.input<typeof MetricPropertyFilterApi>
export type MetricPropertyFilterApiOutput = zod.output<typeof MetricPropertyFilterApi>

export const SpanPropertyFilterTypeApi = zod.enum(['span', 'span_attribute', 'span_resource_attribute'])

export type SpanPropertyFilterTypeApi = zod.input<typeof SpanPropertyFilterTypeApi>
export type SpanPropertyFilterTypeApiOutput = zod.output<typeof SpanPropertyFilterTypeApi>

export const SpanPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: SpanPropertyFilterTypeApi,
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type SpanPropertyFilterApi = zod.input<typeof SpanPropertyFilterApi>
export type SpanPropertyFilterApiOutput = zod.output<typeof SpanPropertyFilterApi>

export const revenueAnalyticsPropertyFilterApiTypeDefault = `revenue_analytics`

export const RevenueAnalyticsPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('revenue_analytics').default(revenueAnalyticsPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type RevenueAnalyticsPropertyFilterApi = zod.input<typeof RevenueAnalyticsPropertyFilterApi>
export type RevenueAnalyticsPropertyFilterApiOutput = zod.output<typeof RevenueAnalyticsPropertyFilterApi>

export const accountCustomPropertyFilterApiTypeDefault = `account_custom_property`

export const AccountCustomPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('account_custom_property')
        .default(accountCustomPropertyFilterApiTypeDefault)
        .describe('Customer analytics account custom property — the key is the property definition id'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type AccountCustomPropertyFilterApi = zod.input<typeof AccountCustomPropertyFilterApi>
export type AccountCustomPropertyFilterApiOutput = zod.output<typeof AccountCustomPropertyFilterApi>

export const workflowVariablePropertyFilterApiTypeDefault = `workflow_variable`

export const WorkflowVariablePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('workflow_variable').default(workflowVariablePropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type WorkflowVariablePropertyFilterApi = zod.input<typeof WorkflowVariablePropertyFilterApi>
export type WorkflowVariablePropertyFilterApiOutput = zod.output<typeof WorkflowVariablePropertyFilterApi>
