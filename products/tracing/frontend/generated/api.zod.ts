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

/**
 * Manage tracing product configuration for this project's canonical environment.
 * Members can read; writing requires project admin, matching the admin-only
 * settings UI. Mirrors the env-router action so /api/projects/:id/tracing_config/
 * resolves alongside the legacy /api/environments/:id/tracing_config/ alias.
 */
export const organizationsProjectsTracingConfigPartialUpdateBodyTracingDistinctIdAttributeKeysItemMax = 200

export const organizationsProjectsTracingConfigPartialUpdateBodyTracingDistinctIdAttributeKeysMax = 10

export const organizationsProjectsTracingConfigPartialUpdateBodyTracingSessionIdAttributeKeysItemMax = 200

export const organizationsProjectsTracingConfigPartialUpdateBodyTracingSessionIdAttributeKeysMax = 10

export const OrganizationsProjectsTracingConfigPartialUpdateBody = /* @__PURE__ */ zod.object({
    tracing_distinct_id_attribute_keys: zod
        .array(
            zod.string().max(organizationsProjectsTracingConfigPartialUpdateBodyTracingDistinctIdAttributeKeysItemMax)
        )
        .max(organizationsProjectsTracingConfigPartialUpdateBodyTracingDistinctIdAttributeKeysMax)
        .optional()
        .describe(
            "Span or resource attribute keys whose values should match a person's distinct_id — a span links to a person when any of these attributes holds one of their distinct IDs. Defaults to ['posthogDistinctId'], the key the posthog-js \/ posthog-react-native SDKs attach to the OTel signals they emit. Add keys only if your pipeline emits the person identifier under different attributes."
        ),
    tracing_session_id_attribute_keys: zod
        .array(
            zod.string().max(organizationsProjectsTracingConfigPartialUpdateBodyTracingSessionIdAttributeKeysItemMax)
        )
        .max(organizationsProjectsTracingConfigPartialUpdateBodyTracingSessionIdAttributeKeysMax)
        .optional()
        .describe(
            "Ordered list of span or resource attribute keys whose values hold the PostHog session ID. Detection checks keys in order, then falls back to common session ID attribute conventions; the first key with a value wins. Defaults to ['sessionId'], the key the posthog-js \/ posthog-react-native SDKs attach to the OTel signals they emit. Add keys only if your pipeline emits the session ID under different attributes."
        ),
    retention_days: zod
        .number()
        .optional()
        .describe(
            'How long spans are kept before they are deleted, in days. Applied at ingest, so a change only affects spans received after it. Can be changed at most once per 24 hours. Span retention rules override this period for the spans they match.'
        ),
})

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesCreateBodyNameMax = 255

export const tracingRetentionRulesCreateBodyEnabledDefault = false
export const tracingRetentionRulesCreateBodyPriorityMin = 0

export const TracingRetentionRulesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(tracingRetentionRulesCreateBodyNameMax).describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(tracingRetentionRulesCreateBodyEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(tracingRetentionRulesCreateBodyPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    config: zod
        .unknown()
        .describe(
            'Retention rule JSON. Required keys: `retention_days` (integer — how long matching logs are kept; must be a tier the organization is entitled to, same as the team-wide Logs retention setting) and `filter_group` (PropertyGroupFilter shape — an AND\/OR tree of property predicates evaluated per record to decide which logs this rule matches). Example: `{\"retention_days\":30,\"filter_group\":{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\"}]}]}}`. Logs matching no enabled rule keep the environment\'s default retention.'
        ),
})

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesUpdateBodyNameMax = 255

export const tracingRetentionRulesUpdateBodyEnabledDefault = false
export const tracingRetentionRulesUpdateBodyPriorityMin = 0

export const TracingRetentionRulesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(tracingRetentionRulesUpdateBodyNameMax).describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(tracingRetentionRulesUpdateBodyEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(tracingRetentionRulesUpdateBodyPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    config: zod
        .unknown()
        .describe(
            'Retention rule JSON. Required keys: `retention_days` (integer — how long matching logs are kept; must be a tier the organization is entitled to, same as the team-wide Logs retention setting) and `filter_group` (PropertyGroupFilter shape — an AND\/OR tree of property predicates evaluated per record to decide which logs this rule matches). Example: `{\"retention_days\":30,\"filter_group\":{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\"}]}]}}`. Logs matching no enabled rule keep the environment\'s default retention.'
        ),
})

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesPartialUpdateBodyNameMax = 255

export const tracingRetentionRulesPartialUpdateBodyEnabledDefault = false
export const tracingRetentionRulesPartialUpdateBodyPriorityMin = 0

export const TracingRetentionRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tracingRetentionRulesPartialUpdateBodyNameMax)
        .optional()
        .describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(tracingRetentionRulesPartialUpdateBodyEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(tracingRetentionRulesPartialUpdateBodyPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Retention rule JSON. Required keys: `retention_days` (integer — how long matching logs are kept; must be a tier the organization is entitled to, same as the team-wide Logs retention setting) and `filter_group` (PropertyGroupFilter shape — an AND\/OR tree of property predicates evaluated per record to decide which logs this rule matches). Example: `{\"retention_days\":30,\"filter_group\":{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\"}]}]}}`. Logs matching no enabled rule keep the environment\'s default retention.'
        ),
})

/**
 * Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1).
 */
export const TracingRetentionRulesReorderCreateBody = /* @__PURE__ */ zod.object({
    ordered_ids: zod
        .array(zod.uuid())
        .describe(
            'Rule IDs in the desired evaluation order (first element is highest priority \/ lowest order index).'
        ),
})

/**
 * Suggest a human-readable name for a retention rule from its retention tier and filter group. Used by the create form as an auto-suggest; nothing is persisted. Returns an empty name when a suggestion can't be generated.
 */
export const TracingRetentionRulesSuggestNameCreateBody = /* @__PURE__ */ zod.object({
    retention_days: zod.number().describe('Retention tier the rule would assign, in days.'),
    filter_group: zod.unknown().describe('PropertyGroupFilter tree the rule would match on.'),
})

export const tracingSpansAggregateCreateBodyQueryOneCompareFilterOneCompareDefault = false
export const tracingSpansAggregateCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansAggregateCreateBodyQueryOneLimitMax = 5000

export const tracingSpansAggregateCreateBodyQueryOneOffsetMin = 0

export const tracingSpansAggregateCreateBodyQueryOneIncludeImpactDefault = false

export const TracingSpansAggregateCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the primary window. Defaults to last hour.'),
            compareFilter: zod
                .object({
                    compare: zod
                        .boolean()
                        .default(tracingSpansAggregateCreateBodyQueryOneCompareFilterOneCompareDefault)
                        .describe(
                            'When true, also fetch results for a comparison window and return them under `compare`.'
                        ),
                    compare_to: zod
                        .string()
                        .nullish()
                        .describe(
                            "Relative date offset for the comparison window (e.g. '-1h', '-1d', '-7d'). Defaults to the immediately previous period of equal length."
                        ),
                })
                .optional()
                .describe(
                    'Optional comparison-window configuration. When omitted, only the primary window is returned.'
                ),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
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
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansAggregateCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters applied to spans in both windows.'),
            limit: zod
                .number()
                .min(1)
                .max(tracingSpansAggregateCreateBodyQueryOneLimitMax)
                .optional()
                .describe(
                    'Max rows to return, ordered by total_duration_nano DESC. Defaults to 100; hard max 5000. Keep this small to bound the response size — a high value on high-cardinality span names (e.g. untemplated URL paths) returns a very large payload. Prefer narrowing with `serviceNames`\/`filterGroup` over raising the limit.'
                ),
            offset: zod
                .number()
                .min(tracingSpansAggregateCreateBodyQueryOneOffsetMin)
                .optional()
                .describe(
                    'Row offset for pagination. Combine with `limit` and the `next_offset` returned in the response to page through results beyond the first page.'
                ),
            includeImpact: zod
                .boolean()
                .default(tracingSpansAggregateCreateBodyQueryOneIncludeImpactDefault)
                .describe(
                    'Also return the sessions and people behind each operation. Off by default because it reads the span and resource attribute maps, which the rest of the aggregation never touches.'
                ),
        })
        .describe('The span aggregation query to execute.'),
})

export const tracingSpansAttributeBreakdownCreateBodyQueryOneExcludeBreakdownFilterDefault = false
export const tracingSpansAttributeBreakdownCreateBodyQueryOneCompareFilterOneCompareDefault = false
export const tracingSpansAttributeBreakdownCreateBodyQueryOneFilterGroupDefault = []

export const TracingSpansAttributeBreakdownCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            breakdownKey: zod
                .string()
                .describe(
                    'Attribute key to group by (e.g. \"server.address\", \"http.response.status_code\"). Discover keys with apm-attributes-list. For the \"span\" breakdown type, must be one of the allowlisted top-level columns: \"service_name\", \"status_code\".'
                ),
            breakdownType: zod
                .enum(['span', 'span_attribute', 'span_resource_attribute'])
                .describe(
                    '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                )
                .describe(
                    'Where the key lives: \"span\" for allowlisted top-level span columns, \"span_attribute\" for span-level attributes, \"span_resource_attribute\" for resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                ),
            excludeBreakdownFilter: zod
                .boolean()
                .default(tracingSpansAttributeBreakdownCreateBodyQueryOneExcludeBreakdownFilterDefault)
                .describe(
                    "Drop filters targeting the breakdown key itself (including serviceNames for a service_name breakdown), so a facet's value list stays complete while one of its values is selected."
                ),
            facetSearch: zod
                .string()
                .optional()
                .describe(
                    "Type-ahead filter over the breakdown field's own values (case-insensitive substring match). An empty string means no filter. Lets a facet's value search reach past the row limit."
                ),
            orderBy: zod
                .enum(['count', 'error_count'])
                .describe('\* `count` - count\n\* `error_count` - error_count')
                .optional()
                .describe(
                    'Order rows by span count or error count, descending. Defaults to count.\n\n\* `count` - count\n\* `error_count` - error_count'
                ),
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the primary window. Defaults to last hour.'),
            compareFilter: zod
                .object({
                    compare: zod
                        .boolean()
                        .default(tracingSpansAttributeBreakdownCreateBodyQueryOneCompareFilterOneCompareDefault)
                        .describe(
                            'When true, also fetch results for a comparison window and return them under `compare`.'
                        ),
                    compare_to: zod
                        .string()
                        .nullish()
                        .describe(
                            "Relative date offset for the comparison window (e.g. '-1h', '-1d', '-7d'). Defaults to the immediately previous period of equal length."
                        ),
                })
                .optional()
                .describe(
                    'Optional comparison-window configuration. When omitted, only the primary window is returned.'
                ),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
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
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansAttributeBreakdownCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters scoping the spans the breakdown runs over (e.g. only error spans).'),
        })
        .describe('The attribute breakdown query to execute.'),
})

export const TracingSpansCountCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the count. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            filterGroup: zod
                .union([
                    zod
                        .array(
                            zod.object({
                                key: zod
                                    .string()
                                    .describe(
                                        'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                                    ),
                                type: zod
                                    .enum(['span', 'span_attribute', 'span_resource_attribute'])
                                    .describe(
                                        '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                                    )
                                    .describe(
                                        '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                                    ),
                                operator: zod
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
                                        'is_set',
                                        'is_not_set',
                                    ])
                                    .describe(
                                        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                                    )
                                    .describe(
                                        'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                                    ),
                                value: zod
                                    .unknown()
                                    .optional()
                                    .describe(
                                        'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                                    ),
                            })
                        )
                        .describe('A flat list of filters, combined with AND.'),
                    zod
                        .object({
                            type: zod.enum(['AND', 'OR']).describe('How the inner groups combine.'),
                            values: zod
                                .array(
                                    zod.object({
                                        type: zod
                                            .enum(['AND', 'OR'])
                                            .describe('How the filters in this group combine.'),
                                        values: zod
                                            .array(
                                                zod.object({
                                                    key: zod
                                                        .string()
                                                        .describe(
                                                            'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                                                        ),
                                                    type: zod
                                                        .enum(['span', 'span_attribute', 'span_resource_attribute'])
                                                        .describe(
                                                            '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                                                        )
                                                        .describe(
                                                            '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                                                        ),
                                                    operator: zod
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
                                                            'is_set',
                                                            'is_not_set',
                                                        ])
                                                        .describe(
                                                            '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                                                        )
                                                        .describe(
                                                            'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                                                        ),
                                                    value: zod
                                                        .unknown()
                                                        .optional()
                                                        .describe(
                                                            'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                                                        ),
                                                })
                                            )
                                            .describe('The property filters in this group.'),
                                    })
                                )
                                .describe('The inner filter groups.'),
                        })
                        .describe('A nested group of filter groups, as the UI filter editor builds it.'),
                ])
                .optional()
                .describe('Property filters for the count. Either a flat list of filters or a nested filter group.'),
        })
        .describe('The span count query to execute.'),
})

export const tracingSpansDurationHistogramCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansDurationHistogramCreateBodyQueryOneRootSpansDefault = true

export const TracingSpansDurationHistogramCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the query. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
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
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansDurationHistogramCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            rootSpans: zod
                .boolean()
                .default(tracingSpansDurationHistogramCreateBodyQueryOneRootSpansDefault)
                .describe(
                    'When true (default), bucket root-span durations only — a distribution of traces. When false, bucket every matching span — used with a span name filter for operation-scoped distributions.'
                ),
        })
        .describe('The duration-histogram query to execute.'),
})

/**
 * Count the exceptions the spans in view hit, by trace, by span and by session, for the
 * span list's error badges.
 *
 * A caller asks about the id kinds it has, and each kind is a separate lookup.
 */
export const tracingSpansErrorCountsCreateBodyTraceIdsMax = 200

export const tracingSpansErrorCountsCreateBodySpanIdsMax = 200

export const tracingSpansErrorCountsCreateBodySessionIdsMax = 200

export const TracingSpansErrorCountsCreateBody = /* @__PURE__ */ zod.object({
    traceIds: zod
        .array(zod.string())
        .max(tracingSpansErrorCountsCreateBodyTraceIdsMax)
        .optional()
        .describe(
            "Hex trace IDs to count exceptions for, matched against the exception's `$trace_id` property. Case insensitive. At most 200 per request."
        ),
    spanIds: zod
        .array(zod.string())
        .max(tracingSpansErrorCountsCreateBodySpanIdsMax)
        .optional()
        .describe(
            "Hex span IDs to count exceptions for, matched against the exception's `$span_id` property. Only counted within the requested traces, so `traceIds` is required alongside. At most 200 per request."
        ),
    sessionIds: zod
        .array(zod.string())
        .max(tracingSpansErrorCountsCreateBodySessionIdsMax)
        .optional()
        .describe(
            'Session IDs to count exceptions for. The fallback for exceptions that carry no trace ID. At most 200 per request.'
        ),
    dateFrom: zod.iso.datetime({ offset: true }).describe('Start of the window the exceptions must fall in. ISO 8601.'),
    dateTo: zod.iso.datetime({ offset: true }).describe('End of the window the exceptions must fall in. ISO 8601.'),
})

export const TracingSpansImpactCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the count. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            filterGroup: zod
                .union([
                    zod
                        .array(
                            zod.object({
                                key: zod
                                    .string()
                                    .describe(
                                        'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                                    ),
                                type: zod
                                    .enum(['span', 'span_attribute', 'span_resource_attribute'])
                                    .describe(
                                        '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                                    )
                                    .describe(
                                        '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                                    ),
                                operator: zod
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
                                        'is_set',
                                        'is_not_set',
                                    ])
                                    .describe(
                                        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                                    )
                                    .describe(
                                        'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                                    ),
                                value: zod
                                    .unknown()
                                    .optional()
                                    .describe(
                                        'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                                    ),
                            })
                        )
                        .describe('A flat list of filters, combined with AND.'),
                    zod
                        .object({
                            type: zod.enum(['AND', 'OR']).describe('How the inner groups combine.'),
                            values: zod
                                .array(
                                    zod.object({
                                        type: zod
                                            .enum(['AND', 'OR'])
                                            .describe('How the filters in this group combine.'),
                                        values: zod
                                            .array(
                                                zod.object({
                                                    key: zod
                                                        .string()
                                                        .describe(
                                                            'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                                                        ),
                                                    type: zod
                                                        .enum(['span', 'span_attribute', 'span_resource_attribute'])
                                                        .describe(
                                                            '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                                                        )
                                                        .describe(
                                                            '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                                                        ),
                                                    operator: zod
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
                                                            'is_set',
                                                            'is_not_set',
                                                        ])
                                                        .describe(
                                                            '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                                                        )
                                                        .describe(
                                                            'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                                                        ),
                                                    value: zod
                                                        .unknown()
                                                        .optional()
                                                        .describe(
                                                            'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                                                        ),
                                                })
                                            )
                                            .describe('The property filters in this group.'),
                                    })
                                )
                                .describe('The inner filter groups.'),
                        })
                        .describe('A nested group of filter groups, as the UI filter editor builds it.'),
                ])
                .optional()
                .describe('Property filters for the count. Either a flat list of filters or a nested filter group.'),
        })
        .describe('The impact query to execute. Takes the same filters as the count query.'),
})

export const tracingSpansLatencyHeatmapCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansLatencyHeatmapCreateBodyQueryOneRootSpansDefault = true

export const TracingSpansLatencyHeatmapCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the query. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
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
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansLatencyHeatmapCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            rootSpans: zod
                .boolean()
                .default(tracingSpansLatencyHeatmapCreateBodyQueryOneRootSpansDefault)
                .describe(
                    'When true (default), bucket root-span durations only — a distribution of traces. When false, bucket every matching span — used with a span name filter for operation-scoped distributions.'
                ),
        })
        .describe('The latency-heatmap query to execute.'),
})

export const tracingSpansQueryCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansQueryCreateBodyQueryOneLimitDefault = 100
export const tracingSpansQueryCreateBodyQueryOneOffsetMin = 0

export const tracingSpansQueryCreateBodyQueryOneRootSpansDefault = true
export const tracingSpansQueryCreateBodyQueryOneFlatSpansDefault = false
export const tracingSpansQueryCreateBodyQueryOneExcludeAttributesDefault = false

export const TracingSpansQueryCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the query. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            orderBy: zod
                .enum(['timestamp', 'duration'])
                .describe('\* `timestamp` - timestamp\n\* `duration` - duration')
                .optional()
                .describe(
                    "Column to order by. Defaults to timestamp. Ordering by timestamp paginates via the keyset cursor ('after'); ordering by duration paginates via 'offset'.\n\n\* `timestamp` - timestamp\n\* `duration` - duration"
                ),
            orderDirection: zod
                .enum(['ASC', 'DESC'])
                .describe('\* `ASC` - ASC\n\* `DESC` - DESC')
                .optional()
                .describe(
                    'Order direction. Defaults to DESC (e.g. timestamp+DESC = newest first, duration+DESC = slowest first).\n\n\* `ASC` - ASC\n\* `DESC` - DESC'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
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
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansQueryCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            traceId: zod.string().optional().describe('Filter to a specific trace ID (hex string).'),
            limit: zod
                .number()
                .default(tracingSpansQueryCreateBodyQueryOneLimitDefault)
                .describe('Max results (1-1000). Defaults to 100.'),
            after: zod
                .string()
                .optional()
                .describe('Keyset pagination cursor from a previous timestamp-ordered response.'),
            offset: zod
                .number()
                .min(tracingSpansQueryCreateBodyQueryOneOffsetMin)
                .optional()
                .describe('Pagination offset, used when ordering by a column (e.g. duration). Defaults to 0.'),
            rootSpans: zod
                .boolean()
                .default(tracingSpansQueryCreateBodyQueryOneRootSpansDefault)
                .describe('Filter to root spans only. Defaults to true.'),
            flatSpans: zod
                .boolean()
                .default(tracingSpansQueryCreateBodyQueryOneFlatSpansDefault)
                .describe(
                    'Return the matching spans themselves, one row per span (root and child), instead of collapsing to traces. Use this to search by a child-span attribute (e.g. code.filepath) without the whole-trace grouping. Distinct from rootSpans. Defaults to false.'
                ),
            prefetchSpans: zod.number().optional().describe('Number of child spans to prefetch per trace (1-100).'),
            excludeAttributes: zod
                .boolean()
                .default(tracingSpansQueryCreateBodyQueryOneExcludeAttributesDefault)
                .describe(
                    'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
                ),
        })
        .describe('The tracing spans query to execute.'),
})

export const tracingSpansSparklineCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansSparklineCreateBodyQueryOneRootSpansDefault = false

export const TracingSpansSparklineCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the query. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
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
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansSparklineCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            rootSpans: zod
                .boolean()
                .default(tracingSpansSparklineCreateBodyQueryOneRootSpansDefault)
                .describe(
                    "When true, count only root spans (one per trace) so the bars reflect the Traces view. When false (default), count every matching span — the Spans view's volume."
                ),
        })
        .describe('The sparkline query to execute.'),
})

export const TracingSpansSymbolStatsCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            filePath: zod
                .string()
                .describe(
                    "Repo-relative path of the source file to aggregate (e.g. 'src\/flags\/flag_matching.rs'). Matched as a path suffix against the recorded OTel code.file.path \/ code.filepath, so a recorded path carrying an extra crate\/workspace prefix still matches. Separators are normalized."
                ),
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe(
                    'Current period to aggregate over; the prior equal-length window is the comparison. Defaults to last 24h.'
                ),
            symbols: zod
                .array(
                    zod.object({
                        name: zod
                            .string()
                            .nullish()
                            .describe(
                                'Opaque identifier (e.g. the function name) echoed back on the matching result row.'
                            ),
                        startLine: zod.number().min(1).describe("First line of the symbol's range, inclusive."),
                        endLine: zod.number().min(1).describe("Last line of the symbol's range, inclusive."),
                    })
                )
                .optional()
                .describe(
                    'Optional symbol (function) line ranges, supplied by the client from its own AST\/LSP. When given, each span is attributed to the smallest enclosing range (one row per symbol). When omitted (or an empty list), spans are aggregated per source line (one row per line); pass a single whole-file range for a file-level total.'
                ),
        })
        .describe('The symbol-stats per-symbol aggregation query to execute.'),
})

export const tracingSpansTraceCreateBodyExcludeAttributesDefault = false
export const tracingSpansTraceCreateBodyOffsetMin = 0

export const TracingSpansTraceCreateBody = /* @__PURE__ */ zod.object({
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .nullish()
                .describe(
                    'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                ),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
        })
        .optional()
        .describe('Date range for the query. Defaults to last 24 hours.'),
    excludeAttributes: zod
        .boolean()
        .default(tracingSpansTraceCreateBodyExcludeAttributesDefault)
        .describe(
            'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
        ),
    offset: zod
        .number()
        .min(tracingSpansTraceCreateBodyOffsetMin)
        .optional()
        .describe(
            "Pagination offset into the trace's spans (ordered by start time ascending). Each page returns up to 2000 spans; pass the response's `nextOffset` to load the next page. Defaults to 0."
        ),
})

export const tracingSpansTreeCreateBodyQueryOneCompareFilterOneCompareDefault = false
export const tracingSpansTreeCreateBodyQueryOneFilterGroupDefault = []

export const TracingSpansTreeCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            spanName: zod
                .string()
                .describe(
                    'Span name to scope the matched trace set. Required because the (trace_id, parent_span_id) self-join is unsafe without bounding the matched traces.'
                ),
            serviceName: zod
                .string()
                .describe(
                    'Service name that scopes the returned tree. Applied to the spans CTE so the call-tree only contains spans from this service, even when matched traces span multiple services.'
                ),
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the primary window. Defaults to last hour.'),
            compareFilter: zod
                .object({
                    compare: zod
                        .boolean()
                        .default(tracingSpansTreeCreateBodyQueryOneCompareFilterOneCompareDefault)
                        .describe(
                            'When true, also fetch results for a comparison window and return them under `compare`.'
                        ),
                    compare_to: zod
                        .string()
                        .nullish()
                        .describe(
                            "Relative date offset for the comparison window (e.g. '-1h', '-1d', '-7d'). Defaults to the immediately previous period of equal length."
                        ),
                })
                .optional()
                .describe(
                    'Optional comparison-window configuration. When omitted, only the primary window is returned.'
                ),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
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
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansTreeCreateBodyQueryOneFilterGroupDefault)
                .describe('Additional property filters applied to spans in both windows.'),
        })
        .describe('The span call-tree aggregation query to execute.'),
})

export const tracingViewsCreateBodyNameMax = 400

export const TracingViewsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tracingViewsCreateBodyNameMax)
        .describe('Human-readable name shown in the saved views list.'),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.'
        ),
    pinned: zod.boolean().optional().describe('Whether the view is pinned for quick access.'),
})

export const tracingViewsUpdateBodyNameMax = 400

export const TracingViewsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tracingViewsUpdateBodyNameMax)
        .describe('Human-readable name shown in the saved views list.'),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.'
        ),
    pinned: zod.boolean().optional().describe('Whether the view is pinned for quick access.'),
})

export const tracingViewsPartialUpdateBodyNameMax = 400

export const TracingViewsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tracingViewsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name shown in the saved views list.'),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.'
        ),
    pinned: zod.boolean().optional().describe('Whether the view is pinned for quick access.'),
})
