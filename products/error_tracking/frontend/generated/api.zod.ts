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

export const errorTrackingAssignmentRulesCreateBodyOrderKeyDefault = 0

export const ErrorTrackingAssignmentRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
        .describe('Property-group filters that define when this rule matches incoming error events.'),
    assignee: zod
        .object({
            type: zod
                .enum(['user', 'role'])
                .describe('\* `user` - user\n\* `role` - role')
                .describe(
                    'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n\* `user` - user\n\* `role` - role'
                ),
            id: zod
                .union([zod.number(), zod.uuid()])
                .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
        })
        .describe('User or role to assign matching issues to.'),
    order_key: zod
        .number()
        .default(errorTrackingAssignmentRulesCreateBodyOrderKeyDefault)
        .describe(
            'Evaluation priority among rules; lower is evaluated first and the first matching rule wins. Defaults to 0. Pass distinct ascending values when creating several rules at once to give them a deterministic order.'
        ),
})

export const ErrorTrackingAssignmentRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .union([
            zod
                .record(zod.string(), zod.unknown())
                .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'),
            zod.null(),
        ])
        .optional()
        .describe('Property-group filters that define when this rule matches incoming error events.'),
    assignee: zod
        .union([
            zod.object({
                type: zod
                    .enum(['user', 'role'])
                    .describe('\* `user` - user\n\* `role` - role')
                    .describe(
                        'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n\* `user` - user\n\* `role` - role'
                    ),
                id: zod
                    .union([zod.number(), zod.uuid()])
                    .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('User or role to assign matching issues to.'),
})

export const ErrorTrackingAssignmentRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .union([
            zod
                .record(zod.string(), zod.unknown())
                .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'),
            zod.null(),
        ])
        .optional()
        .describe('Property-group filters that define when this rule matches incoming error events.'),
    assignee: zod
        .union([
            zod.object({
                type: zod
                    .enum(['user', 'role'])
                    .describe('\* `user` - user\n\* `role` - role')
                    .describe(
                        'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n\* `user` - user\n\* `role` - role'
                    ),
                id: zod
                    .union([zod.number(), zod.uuid()])
                    .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('User or role to assign matching issues to.'),
})

export const ErrorTrackingAssignmentRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod.number().optional(),
    disabled_data: zod.unknown().optional(),
})

export const ErrorTrackingBypassRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
        .describe(
            'Property-group filters that define which incoming error events bypass rate limiting. Must contain at least one filter — empty rules are rejected. To stop rate limiting entirely, adjust the rate limit settings instead of creating a match-all bypass rule.'
        ),
})

export const ErrorTrackingBypassRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
        .optional()
        .describe(
            'Property-group filters that define which incoming error events bypass rate limiting. Must contain at least one filter. Omit to preserve the existing filters.'
        ),
})

export const ErrorTrackingBypassRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
        .optional()
        .describe(
            'Property-group filters that define which incoming error events bypass rate limiting. Must contain at least one filter. Omit to preserve the existing filters.'
        ),
})

export const ErrorTrackingBypassRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
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
})

export const ErrorTrackingExternalReferencesCreateBody = /* @__PURE__ */ zod.object({
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
})

export const ErrorTrackingGroupingRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
        .describe('Property-group filters that define which exceptions should be grouped into the same issue.'),
    assignee: zod
        .union([
            zod.object({
                type: zod
                    .enum(['user', 'role'])
                    .describe('\* `user` - user\n\* `role` - role')
                    .describe(
                        'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n\* `user` - user\n\* `role` - role'
                    ),
                id: zod
                    .union([zod.number(), zod.uuid()])
                    .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Optional user or role to assign to issues created by this grouping rule.'),
    description: zod
        .string()
        .nullish()
        .describe('Optional human-readable description of what this grouping rule is for.'),
})

export const ErrorTrackingGroupingRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .union([
            zod
                .record(zod.string(), zod.unknown())
                .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'),
            zod.null(),
        ])
        .optional()
        .describe(
            'Property-group filters that define which exceptions should be grouped into the same issue. Omit to preserve the existing filters.'
        ),
})

export const ErrorTrackingGroupingRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .union([
            zod
                .record(zod.string(), zod.unknown())
                .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'),
            zod.null(),
        ])
        .optional()
        .describe(
            'Property-group filters that define which exceptions should be grouped into the same issue. Omit to preserve the existing filters.'
        ),
})

export const ErrorTrackingGroupingRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    description: zod.string().nullish(),
    order_key: zod.number().optional(),
    disabled_data: zod.unknown().optional(),
})

export const ErrorTrackingIssuesUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['active', 'resolved', 'suppressed'])
        .describe('\* `active` - active\n\* `resolved` - resolved\n\* `suppressed` - suppressed')
        .optional()
        .describe(
            'Issue status to set. Deprecated archived and pending_release values are rejected.\n\n\* `active` - active\n\* `resolved` - resolved\n\* `suppressed` - suppressed'
        ),
    name: zod.string().nullish().describe('Optional issue display name.'),
    description: zod.string().nullish().describe('Optional issue description.'),
})

export const ErrorTrackingIssuesPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['active', 'resolved', 'suppressed'])
        .describe('\* `active` - active\n\* `resolved` - resolved\n\* `suppressed` - suppressed')
        .optional()
        .describe(
            'Issue status to set. Deprecated archived and pending_release values are rejected.\n\n\* `active` - active\n\* `resolved` - resolved\n\* `suppressed` - suppressed'
        ),
    name: zod.string().nullish().describe('Optional issue display name.'),
    description: zod.string().nullish().describe('Optional issue description.'),
})

export const ErrorTrackingIssuesAssignPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        id: zod.uuid().optional(),
        status: zod.string().optional(),
        name: zod.string().nullish(),
        description: zod.string().nullish(),
        first_seen: zod.iso.datetime({ offset: true }).nullish(),
        fingerprint: zod
            .string()
            .nullish()
            .describe(
                'Deterministic current fingerprint used for issue links, selected by earliest creation time and ID.'
            ),
        assignee: zod
            .union([
                zod.object({
                    id: zod.union([zod.number(), zod.string(), zod.null()]),
                    type: zod.string(),
                }),
                zod.null(),
            ])
            .optional(),
        external_issues: zod
            .array(
                zod.object({
                    id: zod.uuid().describe('Unique ID of the external reference.'),
                    integration: zod
                        .object({
                            id: zod.number().describe('ID of the integration backing this external reference.'),
                            kind: zod
                                .string()
                                .describe("Integration provider, e.g. 'github', 'gitlab', 'linear', or 'jira'."),
                            display_name: zod.string().describe('Human-readable name of the connected integration.'),
                        })
                        .describe('The connected integration this reference was created through.'),
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
            )
            .optional(),
        cohort: zod
            .union([
                zod.object({
                    id: zod.number(),
                    name: zod.string(),
                }),
                zod.null(),
            ])
            .optional(),
    })
    .describe('Read-only serializer for issue contract types returned by the facade.')

export const ErrorTrackingIssuesCohortUpdateBody = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        status: zod.string(),
        name: zod.string().nullable(),
        description: zod.string().nullable(),
        first_seen: zod.iso.datetime({ offset: true }).nullable(),
        fingerprint: zod
            .string()
            .nullable()
            .describe(
                'Deterministic current fingerprint used for issue links, selected by earliest creation time and ID.'
            ),
        assignee: zod.union([
            zod.object({
                id: zod.union([zod.number(), zod.string(), zod.null()]),
                type: zod.string(),
            }),
            zod.null(),
        ]),
        external_issues: zod.array(
            zod.object({
                id: zod.uuid().describe('Unique ID of the external reference.'),
                integration: zod
                    .object({
                        id: zod.number().describe('ID of the integration backing this external reference.'),
                        kind: zod
                            .string()
                            .describe("Integration provider, e.g. 'github', 'gitlab', 'linear', or 'jira'."),
                        display_name: zod.string().describe('Human-readable name of the connected integration.'),
                    })
                    .describe('The connected integration this reference was created through.'),
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
        ),
        cohort: zod.union([
            zod.object({
                id: zod.number(),
                name: zod.string(),
            }),
            zod.null(),
        ]),
    })
    .describe('Read-only serializer for issue contract types returned by the facade.')

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

export const ErrorTrackingIssuesBulkCreateBody = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        status: zod.string(),
        name: zod.string().nullable(),
        description: zod.string().nullable(),
        first_seen: zod.iso.datetime({ offset: true }).nullable(),
        fingerprint: zod
            .string()
            .nullable()
            .describe(
                'Deterministic current fingerprint used for issue links, selected by earliest creation time and ID.'
            ),
        assignee: zod.union([
            zod.object({
                id: zod.union([zod.number(), zod.string(), zod.null()]),
                type: zod.string(),
            }),
            zod.null(),
        ]),
        external_issues: zod.array(
            zod.object({
                id: zod.uuid().describe('Unique ID of the external reference.'),
                integration: zod
                    .object({
                        id: zod.number().describe('ID of the integration backing this external reference.'),
                        kind: zod
                            .string()
                            .describe("Integration provider, e.g. 'github', 'gitlab', 'linear', or 'jira'."),
                        display_name: zod.string().describe('Human-readable name of the connected integration.'),
                    })
                    .describe('The connected integration this reference was created through.'),
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
        ),
        cohort: zod.union([
            zod.object({
                id: zod.number(),
                name: zod.string(),
            }),
            zod.null(),
        ]),
    })
    .describe('Read-only serializer for issue contract types returned by the facade.')

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
        .describe('When true, exclude internal\/test account data from results. Defaults to true.'),
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
        .describe('When true, exclude internal\/test account data from results. Defaults to true.'),
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
                        'Value of your filter. For example `test@example.com` or `https:\/\/example.com\/test\/`. Can be an array for an OR query, like `[\"test@example.com\",\"ok@example.com\"]`'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `gte` - gte\n\* `lte` - lte\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `in` - in\n\* `not_in` - not_in'
                            ),
                        zod.enum(['']),
                        zod.null(),
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
                                'flag',
                                'workflow_variable',
                            ])
                            .describe(
                                '\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
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
        .describe('\* `ASC` - ASC\n\* `DESC` - DESC')
        .default(errorTrackingQueryIssueEventsCreateBodyOrderDirectionDefault)
        .describe('Timestamp sort direction. Defaults to DESC.\n\n\* `ASC` - ASC\n\* `DESC` - DESC'),
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
        .describe('\* `summary` - summary\n\* `stack` - stack\n\* `raw` - raw')
        .default(errorTrackingQueryIssueEventsCreateBodyVerbosityDefault)
        .describe(
            'Controls exception detail size: summary, stack, or raw. Defaults to summary.\n\n\* `summary` - summary\n\* `stack` - stack\n\* `raw` - raw'
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
            '\* `archived` - archived\n\* `active` - active\n\* `resolved` - resolved\n\* `pending_release` - pending_release\n\* `suppressed` - suppressed\n\* `all` - all'
        )
        .default(errorTrackingQueryIssuesListCreateBodyStatusDefault)
        .describe(
            'Filter by issue status. Defaults to active.\n\n\* `archived` - archived\n\* `active` - active\n\* `resolved` - resolved\n\* `pending_release` - pending_release\n\* `suppressed` - suppressed\n\* `all` - all'
        ),
    assignee: zod
        .union([
            zod.object({
                id: zod.union([zod.string(), zod.number(), zod.null()]).describe('User ID or role UUID to filter by.'),
                type: zod
                    .enum(['user', 'role'])
                    .describe('\* `user` - user\n\* `role` - role')
                    .describe('Assignee target type: user or role.\n\n\* `user` - user\n\* `role` - role'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Filter by issue assignee. Omit to include all assignees.'),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingQueryIssuesListCreateBodyFilterTestAccountsDefault)
        .describe('When true, exclude internal\/test account data from results. Defaults to true.'),
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
                        'Value of your filter. For example `test@example.com` or `https:\/\/example.com\/test\/`. Can be an array for an OR query, like `[\"test@example.com\",\"ok@example.com\"]`'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `gte` - gte\n\* `lte` - lte\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `in` - in\n\* `not_in` - not_in'
                            ),
                        zod.enum(['']),
                        zod.null(),
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
                                'flag',
                                'workflow_variable',
                            ])
                            .describe(
                                '\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
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
            '\* `last_seen` - last_seen\n\* `first_seen` - first_seen\n\* `occurrences` - occurrences\n\* `users` - users\n\* `sessions` - sessions'
        )
        .default(errorTrackingQueryIssuesListCreateBodyOrderByDefault)
        .describe(
            'Field used to sort issues. Defaults to occurrences.\n\n\* `last_seen` - last_seen\n\* `first_seen` - first_seen\n\* `occurrences` - occurrences\n\* `users` - users\n\* `sessions` - sessions'
        ),
    orderDirection: zod
        .enum(['ASC', 'DESC'])
        .describe('\* `ASC` - ASC\n\* `DESC` - DESC')
        .default(errorTrackingQueryIssuesListCreateBodyOrderDirectionDefault)
        .describe('Sort direction. Defaults to DESC.\n\n\* `ASC` - ASC\n\* `DESC` - DESC'),
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
        .describe('Filter by SDK\/library value from event $lib, for example posthog-js.'),
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
        .describe('Search user\/email text.'),
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
        .describe('Search stack-frame source\/file path text.'),
})

export const errorTrackingReleasesCreateBodyHashIdMax = 128

export const ErrorTrackingReleasesCreateBody = /* @__PURE__ */ zod.object({
    version: zod.string().describe('Human-readable release version, e.g. a semver string or build number.'),
    project: zod.string().describe('Identifier of the project this release belongs to.'),
    hash_id: zod
        .string()
        .max(errorTrackingReleasesCreateBodyHashIdMax)
        .nullish()
        .describe('Optional client-supplied release hash (e.g. a git commit SHA). Generated server-side when omitted.'),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Optional free-form metadata object stored alongside the release.'),
})

export const errorTrackingReleasesUpdateBodyHashIdMax = 128

export const ErrorTrackingReleasesUpdateBody = /* @__PURE__ */ zod.object({
    version: zod.string().nullish().describe('Human-readable release version. Omit to preserve the current value.'),
    project: zod.string().nullish().describe('Project identifier. Omit to preserve the current value.'),
    hash_id: zod
        .string()
        .max(errorTrackingReleasesUpdateBodyHashIdMax)
        .nullish()
        .describe('Release hash (e.g. a git commit SHA). Omit to preserve the current value.'),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Free-form metadata object. Omit to preserve the current value.'),
})

export const errorTrackingReleasesPartialUpdateBodyHashIdMax = 128

export const ErrorTrackingReleasesPartialUpdateBody = /* @__PURE__ */ zod.object({
    version: zod.string().nullish().describe('Human-readable release version. Omit to preserve the current value.'),
    project: zod.string().nullish().describe('Project identifier. Omit to preserve the current value.'),
    hash_id: zod
        .string()
        .max(errorTrackingReleasesPartialUpdateBodyHashIdMax)
        .nullish()
        .describe('Release hash (e.g. a git commit SHA). Omit to preserve the current value.'),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Free-form metadata object. Omit to preserve the current value.'),
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
    raw_ids: zod.array(zod.string()).describe("Raw frame IDs in 'hash\/part' format to resolve in a single request."),
    symbol_set: zod
        .string()
        .nullish()
        .describe('Optional symbol set reference to scope the lookup to a single symbol set.'),
})

export const errorTrackingSuppressionRulesCreateBodySamplingRateDefault = 1
export const errorTrackingSuppressionRulesCreateBodySamplingRateMin = 0
export const errorTrackingSuppressionRulesCreateBodySamplingRateMax = 1

export const ErrorTrackingSuppressionRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
        .optional()
        .describe(
            'Optional property-group filters that define which incoming error events should be suppressed. Omit this field or provide an empty `values` array to create a match-all suppression rule.'
        ),
    sampling_rate: zod
        .number()
        .min(errorTrackingSuppressionRulesCreateBodySamplingRateMin)
        .max(errorTrackingSuppressionRulesCreateBodySamplingRateMax)
        .default(errorTrackingSuppressionRulesCreateBodySamplingRateDefault)
        .describe(
            'Probability that a matching event is dropped. `1.0` drops every match (default); `0.0` drops none; `0.5` drops half. Higher values suppress more.'
        ),
})

export const errorTrackingSuppressionRulesUpdateBodySamplingRateMin = 0
export const errorTrackingSuppressionRulesUpdateBodySamplingRateMax = 1

export const ErrorTrackingSuppressionRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
        .optional()
        .describe(
            'Property-group filters that define which incoming error events should be suppressed. Provide an empty `values` array to convert the rule into a match-all suppression. Omit to preserve the existing filters.'
        ),
    sampling_rate: zod
        .number()
        .min(errorTrackingSuppressionRulesUpdateBodySamplingRateMin)
        .max(errorTrackingSuppressionRulesUpdateBodySamplingRateMax)
        .optional()
        .describe(
            'Probability that a matching event is dropped. `1.0` drops every match; `0.0` drops none; `0.5` drops half. Higher values suppress more. Omit to preserve the existing rate.'
        ),
})

export const errorTrackingSuppressionRulesPartialUpdateBodySamplingRateMin = 0
export const errorTrackingSuppressionRulesPartialUpdateBodySamplingRateMax = 1

export const ErrorTrackingSuppressionRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
        .optional()
        .describe(
            'Property-group filters that define which incoming error events should be suppressed. Provide an empty `values` array to convert the rule into a match-all suppression. Omit to preserve the existing filters.'
        ),
    sampling_rate: zod
        .number()
        .min(errorTrackingSuppressionRulesPartialUpdateBodySamplingRateMin)
        .max(errorTrackingSuppressionRulesPartialUpdateBodySamplingRateMax)
        .optional()
        .describe(
            'Probability that a matching event is dropped. `1.0` drops every match; `0.0` drops none; `0.5` drops half. Higher values suppress more. Omit to preserve the existing rate.'
        ),
})

export const ErrorTrackingSuppressionRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod.number().optional(),
    disabled_data: zod.unknown().optional(),
    sampling_rate: zod.number().optional(),
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
export const errorTrackingSymbolSetsBulkStartUploadCreateBodySkipOnConflictDefault = false

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
    skip_on_conflict: zod
        .boolean()
        .default(errorTrackingSymbolSetsBulkStartUploadCreateBodySkipOnConflictDefault)
        .describe('Whether to skip uploaded symbol sets whose content hash changed instead of failing.'),
})
