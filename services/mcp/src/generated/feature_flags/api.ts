/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const FeatureFlagsListQueryParams = /* @__PURE__ */ zod.object({
    active: zod.enum(['STALE', 'false', 'true']).optional(),
    created_by_id: zod.string().optional().describe('The User ID which initially created the feature flag.'),
    evaluation_runtime: zod
        .enum(['both', 'client', 'server'])
        .optional()
        .describe('Filter feature flags by their evaluation runtime.'),
    excluded_properties: zod
        .string()
        .optional()
        .describe('JSON-encoded list of feature flag keys to exclude from the results.'),
    has_evaluation_tags: zod
        .enum(['false', 'true'])
        .optional()
        .describe(
            "Filter feature flags by presence of evaluation context tags. 'true' returns only flags with at least one evaluation tag, 'false' returns only flags without evaluation tags."
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Search by feature flag key or name. Case insensitive.'),
    tags: zod.string().optional().describe('JSON-encoded list of tag names to filter feature flags by.'),
    type: zod.enum(['boolean', 'experiment', 'multivariant', 'remote_config']).optional(),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const FeatureFlagsCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().optional().describe('Feature flag key.'),
    name: zod
        .string()
        .optional()
        .describe('Feature flag description (stored in the `name` field for backwards compatibility).'),
    filters: zod
        .object({
            groups: zod
                .array(
                    zod.object({
                        properties: zod
                            .array(
                                zod.union([
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        value: zod
                                            .unknown()
                                            .describe(
                                                'Comparison value for the property filter. Supports strings, numbers, booleans, and arrays.'
                                            ),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `gte` - gte\n* `lt` - lt\n* `lte` - lte'
                                            )
                                            .describe(
                                                'Operator used to compare the property value.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `gte` - gte\n* `lt` - lt\n* `lte` - lte'
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['is_set', 'is_not_set'])
                                            .describe('* `is_set` - is_set\n* `is_not_set` - is_not_set')
                                            .describe(
                                                'Existence operator.\n\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                                            ),
                                        value: zod
                                            .unknown()
                                            .optional()
                                            .describe(
                                                'Optional value. Runtime behavior determines whether this is ignored.'
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['is_date_exact', 'is_date_after', 'is_date_before'])
                                            .describe(
                                                '* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before'
                                            )
                                            .describe(
                                                'Date comparison operator.\n\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before'
                                            ),
                                        value: zod
                                            .string()
                                            .describe('Date value in ISO format or relative date expression.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum([
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                            ])
                                            .describe(
                                                '* `semver_gt` - semver_gt\n* `semver_gte` - semver_gte\n* `semver_lt` - semver_lt\n* `semver_lte` - semver_lte\n* `semver_eq` - semver_eq\n* `semver_neq` - semver_neq\n* `semver_tilde` - semver_tilde\n* `semver_caret` - semver_caret\n* `semver_wildcard` - semver_wildcard'
                                            )
                                            .describe(
                                                'Semantic version comparison operator.\n\n* `semver_gt` - semver_gt\n* `semver_gte` - semver_gte\n* `semver_lt` - semver_lt\n* `semver_lte` - semver_lte\n* `semver_eq` - semver_eq\n* `semver_neq` - semver_neq\n* `semver_tilde` - semver_tilde\n* `semver_caret` - semver_caret\n* `semver_wildcard` - semver_wildcard'
                                            ),
                                        value: zod.string().describe('Semantic version string.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['icontains_multi', 'not_icontains_multi'])
                                            .describe(
                                                '* `icontains_multi` - icontains_multi\n* `not_icontains_multi` - not_icontains_multi'
                                            )
                                            .describe(
                                                'Multi-contains operator.\n\n* `icontains_multi` - icontains_multi\n* `not_icontains_multi` - not_icontains_multi'
                                            ),
                                        value: zod.array(zod.string()).describe('List of strings to evaluate against.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort'])
                                            .describe('* `cohort` - cohort')
                                            .describe(
                                                'Cohort property type required for in/not_in operators.\n\n* `cohort` - cohort'
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['in', 'not_in'])
                                            .describe('* `in` - in\n* `not_in` - not_in')
                                            .describe(
                                                'Membership operator for cohort properties.\n\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                        value: zod
                                            .unknown()
                                            .describe('Cohort comparison value (single or list, depending on usage).'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['flag'])
                                            .describe('* `flag` - flag')
                                            .describe(
                                                'Flag property type required for flag dependency checks.\n\n* `flag` - flag'
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['flag_evaluates_to'])
                                            .describe('* `flag_evaluates_to` - flag_evaluates_to')
                                            .describe(
                                                'Operator for feature flag dependency evaluation.\n\n* `flag_evaluates_to` - flag_evaluates_to'
                                            ),
                                        value: zod.unknown().describe('Value to compare flag evaluation against.'),
                                    }),
                                ])
                            )
                            .optional()
                            .describe('Property conditions for this release condition group.'),
                        rollout_percentage: zod
                            .number()
                            .optional()
                            .describe('Rollout percentage for this release condition group.'),
                        variant: zod.string().nullish().describe('Variant key override for multivariate flags.'),
                        aggregation_group_type_index: zod
                            .number()
                            .nullish()
                            .describe('Group type index for this condition set. None means person-level aggregation.'),
                    })
                )
                .optional()
                .describe('Release condition groups for the feature flag.'),
            multivariate: zod
                .object({
                    variants: zod
                        .array(
                            zod.object({
                                key: zod.string().describe('Unique key for this variant.'),
                                name: zod.string().optional().describe('Human-readable name for this variant.'),
                                rollout_percentage: zod.number().describe('Variant rollout percentage.'),
                            })
                        )
                        .describe('Variant definitions for multivariate feature flags.'),
                })
                .nullish()
                .describe('Multivariate configuration for variant-based rollouts.'),
            aggregation_group_type_index: zod
                .number()
                .nullish()
                .describe('Group type index for group-based feature flags.'),
            payloads: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe('Optional payload values keyed by variant key.'),
            super_groups: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .optional()
                .describe('Additional super condition groups used by experiments.'),
        })
        .optional()
        .describe('Feature flag targeting configuration.'),
    active: zod.boolean().optional().describe('Whether the feature flag is active.'),
    tags: zod.array(zod.string()).optional().describe('Organizational tags for this feature flag.'),
    evaluation_tags: zod
        .array(zod.string())
        .optional()
        .describe('Evaluation context tags. Must be a subset of `tags`.'),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsRetrieve2Params = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const FeatureFlagsPartialUpdateBody = /* @__PURE__ */ zod.object({
    key: zod.string().optional().describe('Feature flag key.'),
    name: zod
        .string()
        .optional()
        .describe('Feature flag description (stored in the `name` field for backwards compatibility).'),
    filters: zod
        .object({
            groups: zod
                .array(
                    zod.object({
                        properties: zod
                            .array(
                                zod.union([
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        value: zod
                                            .unknown()
                                            .describe(
                                                'Comparison value for the property filter. Supports strings, numbers, booleans, and arrays.'
                                            ),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                            ])
                                            .describe(
                                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `gte` - gte\n* `lt` - lt\n* `lte` - lte'
                                            )
                                            .describe(
                                                'Operator used to compare the property value.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `gte` - gte\n* `lt` - lt\n* `lte` - lte'
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['is_set', 'is_not_set'])
                                            .describe('* `is_set` - is_set\n* `is_not_set` - is_not_set')
                                            .describe(
                                                'Existence operator.\n\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                                            ),
                                        value: zod
                                            .unknown()
                                            .optional()
                                            .describe(
                                                'Optional value. Runtime behavior determines whether this is ignored.'
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['is_date_exact', 'is_date_after', 'is_date_before'])
                                            .describe(
                                                '* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before'
                                            )
                                            .describe(
                                                'Date comparison operator.\n\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before'
                                            ),
                                        value: zod
                                            .string()
                                            .describe('Date value in ISO format or relative date expression.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum([
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                            ])
                                            .describe(
                                                '* `semver_gt` - semver_gt\n* `semver_gte` - semver_gte\n* `semver_lt` - semver_lt\n* `semver_lte` - semver_lte\n* `semver_eq` - semver_eq\n* `semver_neq` - semver_neq\n* `semver_tilde` - semver_tilde\n* `semver_caret` - semver_caret\n* `semver_wildcard` - semver_wildcard'
                                            )
                                            .describe(
                                                'Semantic version comparison operator.\n\n* `semver_gt` - semver_gt\n* `semver_gte` - semver_gte\n* `semver_lt` - semver_lt\n* `semver_lte` - semver_lte\n* `semver_eq` - semver_eq\n* `semver_neq` - semver_neq\n* `semver_tilde` - semver_tilde\n* `semver_caret` - semver_caret\n* `semver_wildcard` - semver_wildcard'
                                            ),
                                        value: zod.string().describe('Semantic version string.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('* `cohort` - cohort\n* `person` - person\n* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n* `cohort` - cohort\n* `person` - person\n* `group` - group"
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['icontains_multi', 'not_icontains_multi'])
                                            .describe(
                                                '* `icontains_multi` - icontains_multi\n* `not_icontains_multi` - not_icontains_multi'
                                            )
                                            .describe(
                                                'Multi-contains operator.\n\n* `icontains_multi` - icontains_multi\n* `not_icontains_multi` - not_icontains_multi'
                                            ),
                                        value: zod.array(zod.string()).describe('List of strings to evaluate against.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort'])
                                            .describe('* `cohort` - cohort')
                                            .describe(
                                                'Cohort property type required for in/not_in operators.\n\n* `cohort` - cohort'
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['in', 'not_in'])
                                            .describe('* `in` - in\n* `not_in` - not_in')
                                            .describe(
                                                'Membership operator for cohort properties.\n\n* `in` - in\n* `not_in` - not_in'
                                            ),
                                        value: zod
                                            .unknown()
                                            .describe('Cohort comparison value (single or list, depending on usage).'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['flag'])
                                            .describe('* `flag` - flag')
                                            .describe(
                                                'Flag property type required for flag dependency checks.\n\n* `flag` - flag'
                                            ),
                                        cohort_name: zod
                                            .string()
                                            .nullish()
                                            .describe('Resolved cohort name for cohort-type filters.'),
                                        group_type_index: zod
                                            .number()
                                            .nullish()
                                            .describe('Group type index when using group-based filters.'),
                                        operator: zod
                                            .enum(['flag_evaluates_to'])
                                            .describe('* `flag_evaluates_to` - flag_evaluates_to')
                                            .describe(
                                                'Operator for feature flag dependency evaluation.\n\n* `flag_evaluates_to` - flag_evaluates_to'
                                            ),
                                        value: zod.unknown().describe('Value to compare flag evaluation against.'),
                                    }),
                                ])
                            )
                            .optional()
                            .describe('Property conditions for this release condition group.'),
                        rollout_percentage: zod
                            .number()
                            .optional()
                            .describe('Rollout percentage for this release condition group.'),
                        variant: zod.string().nullish().describe('Variant key override for multivariate flags.'),
                        aggregation_group_type_index: zod
                            .number()
                            .nullish()
                            .describe('Group type index for this condition set. None means person-level aggregation.'),
                    })
                )
                .optional()
                .describe('Release condition groups for the feature flag.'),
            multivariate: zod
                .object({
                    variants: zod
                        .array(
                            zod.object({
                                key: zod.string().describe('Unique key for this variant.'),
                                name: zod.string().optional().describe('Human-readable name for this variant.'),
                                rollout_percentage: zod.number().describe('Variant rollout percentage.'),
                            })
                        )
                        .describe('Variant definitions for multivariate feature flags.'),
                })
                .nullish()
                .describe('Multivariate configuration for variant-based rollouts.'),
            aggregation_group_type_index: zod
                .number()
                .nullish()
                .describe('Group type index for group-based feature flags.'),
            payloads: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe('Optional payload values keyed by variant key.'),
            super_groups: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .optional()
                .describe('Additional super condition groups used by experiments.'),
        })
        .optional()
        .describe('Feature flag targeting configuration.'),
    active: zod.boolean().optional().describe('Whether the feature flag is active.'),
    tags: zod.array(zod.string()).optional().describe('Organizational tags for this feature flag.'),
    evaluation_tags: zod
        .array(zod.string())
        .optional()
        .describe('Evaluation context tags. Must be a subset of `tags`.'),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const FeatureFlagsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
