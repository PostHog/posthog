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

export const ErrorTrackingAssignmentRulesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const ErrorTrackingAssignmentRulesUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const ErrorTrackingAssignmentRulesPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().optional(),
})

export const ErrorTrackingExternalReferencesCreateBody = /* @__PURE__ */ zod.object({
    integration_id: zod.number(),
    config: zod.unknown(),
    issue: zod.uuid(),
})

export const ErrorTrackingGroupingRulesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const errorTrackingGroupingRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    description: zod.string().nullish(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().optional(),
})

export const errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    description: zod.string().nullish(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().optional(),
})

export const errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    description: zod.string().nullish(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().optional(),
})

export const ErrorTrackingIssuesCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '\* `archived` - Archived\n\* `active` - Active\n\* `resolved` - Resolved\n\* `pending_release` - Pending release\n\* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({ offset: true }),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string(), zod.null()]),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod.string(),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '\* `archived` - Archived\n\* `active` - Active\n\* `resolved` - Resolved\n\* `pending_release` - Pending release\n\* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({ offset: true }),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string(), zod.null()]),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod.string(),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '\* `archived` - Archived\n\* `active` - Active\n\* `resolved` - Resolved\n\* `pending_release` - Pending release\n\* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({ offset: true }).optional(),
    assignee: zod
        .object({
            id: zod.union([zod.number(), zod.string(), zod.null()]),
            type: zod.string(),
        })
        .optional(),
    external_issues: zod
        .array(
            zod.object({
                id: zod.uuid(),
                integration: zod.object({
                    id: zod.number(),
                    kind: zod.string(),
                    display_name: zod.string(),
                }),
                integration_id: zod.number(),
                config: zod.unknown(),
                issue: zod.uuid(),
                external_url: zod.string(),
            })
        )
        .optional(),
})

export const ErrorTrackingIssuesAssignPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '\* `archived` - Archived\n\* `active` - Active\n\* `resolved` - Resolved\n\* `pending_release` - Pending release\n\* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({ offset: true }).optional(),
    assignee: zod
        .object({
            id: zod.union([zod.number(), zod.string(), zod.null()]),
            type: zod.string(),
        })
        .optional(),
    external_issues: zod
        .array(
            zod.object({
                id: zod.uuid(),
                integration: zod.object({
                    id: zod.number(),
                    kind: zod.string(),
                    display_name: zod.string(),
                }),
                integration_id: zod.number(),
                config: zod.unknown(),
                issue: zod.uuid(),
                external_url: zod.string(),
            })
        )
        .optional(),
})

export const ErrorTrackingIssuesCohortUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '\* `archived` - Archived\n\* `active` - Active\n\* `resolved` - Resolved\n\* `pending_release` - Pending release\n\* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({ offset: true }),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string(), zod.null()]),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod.string(),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesMergeCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.uuid()).describe('IDs of the issues to merge into the current issue.'),
})

export const ErrorTrackingIssuesSplitCreateBody = /* @__PURE__ */ zod.object({
    fingerprints: zod
        .array(
            zod.object({
                fingerprint: zod.string().describe('Fingerprint to split into a new issue.'),
                name: zod
                    .string()
                    .optional()
                    .describe('Optional name for the new issue created from this fingerprint.'),
                description: zod
                    .string()
                    .optional()
                    .describe('Optional description for the new issue created from this fingerprint.'),
            })
        )
        .optional()
        .describe('Fingerprints to split into new issues. Each fingerprint becomes its own new issue.'),
})

export const ErrorTrackingIssuesBulkCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '\* `archived` - Archived\n\* `active` - Active\n\* `resolved` - Resolved\n\* `pending_release` - Pending release\n\* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({ offset: true }),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string(), zod.null()]),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod.string(),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.uuid(),
            external_url: zod.string(),
        })
    ),
})

/**
 * Fetch one error tracking issue with impact counts, top in_app frame, latest release, and optional sparkline.
 * @summary Get compact error tracking issue details
 */
export const errorTrackingQueryIssueCreateBodyFilterTestAccountsDefault = true
export const errorTrackingQueryIssueCreateBodyVolumeResolutionDefault = 0
export const errorTrackingQueryIssueCreateBodyVolumeResolutionMin = 0
export const errorTrackingQueryIssueCreateBodyVolumeResolutionMax = 200

export const errorTrackingQueryIssueCreateBodyIncludeSparklineDefault = false

export const ErrorTrackingQueryIssueCreateBody = /* @__PURE__ */ zod.object({
    issueId: zod.uuid().describe('Error tracking issue ID.'),
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .optional()
                .describe('Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d.'),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.'),
        })
        .optional()
        .describe('Date range for issue impact and latest-event metadata. Defaults to the last 7 days.'),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingQueryIssueCreateBodyFilterTestAccountsDefault)
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    volumeResolution: zod
        .number()
        .min(errorTrackingQueryIssueCreateBodyVolumeResolutionMin)
        .max(errorTrackingQueryIssueCreateBodyVolumeResolutionMax)
        .default(errorTrackingQueryIssueCreateBodyVolumeResolutionDefault)
        .describe('Volume buckets. Maximum 200.'),
    includeSparkline: zod
        .boolean()
        .default(errorTrackingQueryIssueCreateBodyIncludeSparklineDefault)
        .describe('Set true to include a compact numeric occurrence sparkline. Defaults to false.'),
})

/**
 * Fetch sampled exception events, stack traces, browser/SDK context, URL, and $session_id values for one issue.
 * @summary List sampled exception events for an error tracking issue
 */
export const errorTrackingQueryIssueEventsCreateBodyFilterTestAccountsDefault = true
export const errorTrackingQueryIssueEventsCreateBodyFilterGroupItemOperatorDefault = `exact`
export const errorTrackingQueryIssueEventsCreateBodyFilterGroupItemTypeDefault = `event`
export const errorTrackingQueryIssueEventsCreateBodySearchQueryMax = 500

export const errorTrackingQueryIssueEventsCreateBodyOrderDirectionDefault = `DESC`
export const errorTrackingQueryIssueEventsCreateBodyLimitDefault = 1
export const errorTrackingQueryIssueEventsCreateBodyLimitMax = 20

export const errorTrackingQueryIssueEventsCreateBodyOffsetDefault = 0
export const errorTrackingQueryIssueEventsCreateBodyOffsetMin = 0

export const errorTrackingQueryIssueEventsCreateBodyVerbosityDefault = `summary`
export const errorTrackingQueryIssueEventsCreateBodyOnlyAppFramesDefault = true

export const ErrorTrackingQueryIssueEventsCreateBody = /* @__PURE__ */ zod.object({
    issueId: zod.uuid().describe('Error tracking issue ID.'),
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .optional()
                .describe('Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d.'),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.'),
        })
        .optional()
        .describe('Date range for sampled exception events. Defaults to the last 7 days.'),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingQueryIssueEventsCreateBodyFilterTestAccountsDefault)
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    filterGroup: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe("Key of the property you're filtering on. For example `email` or `$current_url`"),
                value: zod
                    .union([
                        zod.string(),
                        zod.number(),
                        zod.boolean(),
                        zod.array(zod.union([zod.string(), zod.number()])),
                    ])
                    .describe(
                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `[\"test@example.com\",\"ok@example.com\"]`'
                    ),
                operator: zod
                    .union([
                        zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
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
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .default(errorTrackingQueryIssueEventsCreateBodyFilterGroupItemOperatorDefault),
                type: zod
                    .union([
                        zod
                            .enum([
                                'event',
                                'event_metadata',
                                'feature',
                                'person',
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
                                'span',
                                'span_attribute',
                                'span_resource_attribute',
                                'revenue_analytics',
                                'flag',
                                'workflow_variable',
                            ])
                            .describe(
                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                            ),
                        zod.enum(['']),
                    ])
                    .default(errorTrackingQueryIssueEventsCreateBodyFilterGroupItemTypeDefault),
            })
        )
        .optional()
        .describe('Advanced flat AND property filters applied to sampled events. HogQL filters are rejected.'),
    searchQuery: zod
        .string()
        .max(errorTrackingQueryIssueEventsCreateBodySearchQueryMax)
        .optional()
        .describe('Search exception types, exception values, and current URL among sampled events.'),
    orderDirection: zod
        .enum(['ASC', 'DESC'])
        .describe('* `ASC` - ASC\n* `DESC` - DESC')
        .default(errorTrackingQueryIssueEventsCreateBodyOrderDirectionDefault)
        .describe('Timestamp sort direction. Defaults to DESC.\n\n* `ASC` - ASC\n* `DESC` - DESC'),
    limit: zod
        .number()
        .min(1)
        .max(errorTrackingQueryIssueEventsCreateBodyLimitMax)
        .default(errorTrackingQueryIssueEventsCreateBodyLimitDefault)
        .describe('Page size.'),
    offset: zod
        .number()
        .min(errorTrackingQueryIssueEventsCreateBodyOffsetMin)
        .default(errorTrackingQueryIssueEventsCreateBodyOffsetDefault)
        .describe('Pagination offset.'),
    verbosity: zod
        .enum(['summary', 'stack', 'raw'])
        .describe('* `summary` - summary\n* `stack` - stack\n* `raw` - raw')
        .default(errorTrackingQueryIssueEventsCreateBodyVerbosityDefault)
        .describe(
            'Controls exception detail size: summary, stack, or raw. Defaults to summary.\n\n* `summary` - summary\n* `stack` - stack\n* `raw` - raw'
        ),
    onlyAppFrames: zod
        .boolean()
        .default(errorTrackingQueryIssueEventsCreateBodyOnlyAppFramesDefault)
        .describe('When true, include only stack frames marked in_app. Defaults to true.'),
})

/**
 * List error tracking issues with typed filters and compact aggregate counts.
 * @summary List compact error tracking issues
 */
export const errorTrackingQueryIssuesListCreateBodyStatusDefault = `active`
export const errorTrackingQueryIssuesListCreateBodyFilterTestAccountsDefault = true
export const errorTrackingQueryIssuesListCreateBodySearchQueryMax = 500

export const errorTrackingQueryIssuesListCreateBodyFilterGroupItemOperatorDefault = `exact`
export const errorTrackingQueryIssuesListCreateBodyFilterGroupItemTypeDefault = `event`
export const errorTrackingQueryIssuesListCreateBodyOrderByDefault = `occurrences`
export const errorTrackingQueryIssuesListCreateBodyOrderDirectionDefault = `DESC`
export const errorTrackingQueryIssuesListCreateBodyLimitDefault = 25
export const errorTrackingQueryIssuesListCreateBodyLimitMax = 100

export const errorTrackingQueryIssuesListCreateBodyOffsetDefault = 0
export const errorTrackingQueryIssuesListCreateBodyOffsetMin = 0

export const errorTrackingQueryIssuesListCreateBodyVolumeResolutionDefault = 0
export const errorTrackingQueryIssuesListCreateBodyVolumeResolutionMin = 0
export const errorTrackingQueryIssuesListCreateBodyVolumeResolutionMax = 200

export const errorTrackingQueryIssuesListCreateBodyReleaseMax = 500

export const errorTrackingQueryIssuesListCreateBodyUserMax = 500

export const errorTrackingQueryIssuesListCreateBodyUrlMax = 1000

export const errorTrackingQueryIssuesListCreateBodyFilePathMax = 1000

export const ErrorTrackingQueryIssuesListCreateBody = /* @__PURE__ */ zod.object({
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .optional()
                .describe('Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d.'),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.'),
        })
        .optional()
        .describe('Date range for issue aggregates. Defaults to the last 7 days.'),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all'])
        .describe(
            '* `archived` - archived\n* `active` - active\n* `resolved` - resolved\n* `pending_release` - pending_release\n* `suppressed` - suppressed\n* `all` - all'
        )
        .default(errorTrackingQueryIssuesListCreateBodyStatusDefault)
        .describe(
            'Filter by issue status. Defaults to active.\n\n* `archived` - archived\n* `active` - active\n* `resolved` - resolved\n* `pending_release` - pending_release\n* `suppressed` - suppressed\n* `all` - all'
        ),
    assignee: zod
        .object({
            id: zod.union([zod.string(), zod.number()]).describe('User ID or role UUID to filter by.'),
            type: zod
                .enum(['user', 'role'])
                .describe('* `user` - user\n* `role` - role')
                .describe('Assignee target type: user or role.\n\n* `user` - user\n* `role` - role'),
        })
        .nullish()
        .describe('Filter by issue assignee. Omit to include all assignees.'),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingQueryIssuesListCreateBodyFilterTestAccountsDefault)
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    searchQuery: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodySearchQueryMax)
        .optional()
        .describe('Free-text search across exception types, values, stack frames, and email fields.'),
    filterGroup: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe("Key of the property you're filtering on. For example `email` or `$current_url`"),
                value: zod
                    .union([
                        zod.string(),
                        zod.number(),
                        zod.boolean(),
                        zod.array(zod.union([zod.string(), zod.number()])),
                    ])
                    .describe(
                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `[\"test@example.com\",\"ok@example.com\"]`'
                    ),
                operator: zod
                    .union([
                        zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
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
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .default(errorTrackingQueryIssuesListCreateBodyFilterGroupItemOperatorDefault),
                type: zod
                    .union([
                        zod
                            .enum([
                                'event',
                                'event_metadata',
                                'feature',
                                'person',
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
                                'span',
                                'span_attribute',
                                'span_resource_attribute',
                                'revenue_analytics',
                                'flag',
                                'workflow_variable',
                            ])
                            .describe(
                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                            ),
                        zod.enum(['']),
                    ])
                    .default(errorTrackingQueryIssuesListCreateBodyFilterGroupItemTypeDefault),
            })
        )
        .optional()
        .describe(
            'Advanced flat AND property filters. Prefer typed shortcut fields when they fit. HogQL filters are rejected.'
        ),
    orderBy: zod
        .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])
        .describe(
            '* `last_seen` - last_seen\n* `first_seen` - first_seen\n* `occurrences` - occurrences\n* `users` - users\n* `sessions` - sessions'
        )
        .default(errorTrackingQueryIssuesListCreateBodyOrderByDefault)
        .describe(
            'Field used to sort issues. Defaults to occurrences.\n\n* `last_seen` - last_seen\n* `first_seen` - first_seen\n* `occurrences` - occurrences\n* `users` - users\n* `sessions` - sessions'
        ),
    orderDirection: zod
        .enum(['ASC', 'DESC'])
        .describe('* `ASC` - ASC\n* `DESC` - DESC')
        .default(errorTrackingQueryIssuesListCreateBodyOrderDirectionDefault)
        .describe('Sort direction. Defaults to DESC.\n\n* `ASC` - ASC\n* `DESC` - DESC'),
    limit: zod
        .number()
        .min(1)
        .max(errorTrackingQueryIssuesListCreateBodyLimitMax)
        .default(errorTrackingQueryIssuesListCreateBodyLimitDefault)
        .describe('Page size.'),
    offset: zod
        .number()
        .min(errorTrackingQueryIssuesListCreateBodyOffsetMin)
        .default(errorTrackingQueryIssuesListCreateBodyOffsetDefault)
        .describe('Pagination offset.'),
    volumeResolution: zod
        .number()
        .min(errorTrackingQueryIssuesListCreateBodyVolumeResolutionMin)
        .max(errorTrackingQueryIssuesListCreateBodyVolumeResolutionMax)
        .default(errorTrackingQueryIssuesListCreateBodyVolumeResolutionDefault)
        .describe('Number of volume buckets. Defaults to 0 for compact aggregate counts.'),
    library: zod
        .union([zod.string(), zod.array(zod.string()).min(1)])
        .optional()
        .describe('Filter by SDK/library value from event $lib, for example posthog-js.'),
    release: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodyReleaseMax)
        .optional()
        .describe('Filter by exact release ID, version, or git commit ID captured in $exception_releases.'),
    fingerprint: zod
        .union([zod.string(), zod.array(zod.string()).min(1)])
        .optional()
        .describe('Filter by exact exception fingerprint hash, not fuzzy search.'),
    user: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodyUserMax)
        .optional()
        .describe('Search user/email text.'),
    personId: zod.uuid().optional().describe('Filter by exact PostHog person UUID.'),
    url: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodyUrlMax)
        .optional()
        .describe('Filter by current URL substring.'),
    filePath: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodyFilePathMax)
        .optional()
        .describe('Search stack-frame source/file path text.'),
})

export const ErrorTrackingSettingsUpdateSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
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

export const ErrorTrackingSpikeDetectionConfigUpdateConfigPartialUpdateBody = /* @__PURE__ */ zod.object({
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

export const ErrorTrackingStackFramesBatchGetCreateBody = /* @__PURE__ */ zod.object({
    contents: zod.unknown(),
    resolved: zod.boolean(),
    context: zod.unknown().optional(),
    symbol_set_ref: zod.string().optional(),
})

export const ErrorTrackingSuppressionRulesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const errorTrackingSuppressionRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().optional(),
    sampling_rate: zod.number().optional(),
})

export const errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().optional(),
    sampling_rate: zod.number().optional(),
})

export const errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().optional(),
    sampling_rate: zod.number().optional(),
})

export const ErrorTrackingReleasesCreateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().optional(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesUpdateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().optional(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesPartialUpdateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string().optional(),
    metadata: zod.unknown().optional(),
    version: zod.string().optional(),
    project: zod.string().optional(),
})

export const ErrorTrackingSymbolSetsFinishUploadUpdateBody = /* @__PURE__ */ zod.object({
    content_hash: zod.string().describe('Hash of the uploaded symbol set content.'),
})

export const ErrorTrackingSymbolSetsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.uuid()).describe('Symbol set IDs to delete.'),
})

export const ErrorTrackingSymbolSetsBulkFinishUploadCreateBody = /* @__PURE__ */ zod.object({
    content_hashes: zod.record(zod.string(), zod.string()).describe('Map of symbol set ID to uploaded content hash.'),
})

export const errorTrackingSymbolSetsBulkStartUploadCreateBodyForceDefault = false

export const ErrorTrackingSymbolSetsBulkStartUploadCreateBody = /* @__PURE__ */ zod.object({
    chunk_ids: zod
        .array(zod.string())
        .optional()
        .describe('Legacy list of symbol set references to upload, all associated with `release_id`.'),
    release_id: zod.string().nullish().describe('Optional error tracking release ID used with `chunk_ids`.'),
    symbol_sets: zod
        .array(
            zod.object({
                chunk_id: zod.string().describe('Symbol set reference to upload.'),
                release_id: zod
                    .string()
                    .nullish()
                    .describe('Optional error tracking release ID associated with this symbol set.'),
                content_hash: zod
                    .string()
                    .nullish()
                    .describe('Optional hash of the symbol set content, used to skip unchanged uploads.'),
            })
        )
        .optional()
        .describe('Symbol sets to upload with per-symbol release IDs and content hashes.'),
    force: zod
        .boolean()
        .default(errorTrackingSymbolSetsBulkStartUploadCreateBodyForceDefault)
        .describe('Whether to overwrite uploaded symbol sets whose content hash changed.'),
})
