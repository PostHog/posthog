/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 21 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const FeatureFlagsCopyFlagsCreateParams = zod.object({
    organization_id: zod.string(),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const FeatureFlagsListQueryParams = zod.object({
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

export const featureFlagsListResponseResultsItemKeyMax = 400

export const featureFlagsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const featureFlagsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const featureFlagsListResponseResultsItemCreatedByOneLastNameMax = 150

export const featureFlagsListResponseResultsItemCreatedByOneEmailMax = 254

export const featureFlagsListResponseResultsItemVersionDefault = 0
export const featureFlagsListResponseResultsItemLastModifiedByOneDistinctIdMax = 200

export const featureFlagsListResponseResultsItemLastModifiedByOneFirstNameMax = 150

export const featureFlagsListResponseResultsItemLastModifiedByOneLastNameMax = 150

export const featureFlagsListResponseResultsItemLastModifiedByOneEmailMax = 254

export const featureFlagsListResponseResultsItemShouldCreateUsageDashboardDefault = true

export const FeatureFlagsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number().optional(),
                name: zod
                    .string()
                    .optional()
                    .describe(
                        'contains the description for the flag (field name `name` is kept for backwards-compatibility)'
                    ),
                key: zod.string().max(featureFlagsListResponseResultsItemKeyMax),
                filters: zod.record(zod.string(), zod.unknown()).optional(),
                deleted: zod.boolean().optional(),
                active: zod.boolean().optional(),
                created_by: zod
                    .object({
                        id: zod.number().optional(),
                        uuid: zod.string().optional(),
                        distinct_id: zod
                            .string()
                            .max(featureFlagsListResponseResultsItemCreatedByOneDistinctIdMax)
                            .nullish(),
                        first_name: zod
                            .string()
                            .max(featureFlagsListResponseResultsItemCreatedByOneFirstNameMax)
                            .optional(),
                        last_name: zod
                            .string()
                            .max(featureFlagsListResponseResultsItemCreatedByOneLastNameMax)
                            .optional(),
                        email: zod.string().email().max(featureFlagsListResponseResultsItemCreatedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
                    })
                    .optional(),
                created_at: zod.string().datetime({}).optional(),
                updated_at: zod.string().datetime({}).nullish(),
                version: zod.number().default(featureFlagsListResponseResultsItemVersionDefault),
                last_modified_by: zod
                    .object({
                        id: zod.number().optional(),
                        uuid: zod.string().optional(),
                        distinct_id: zod
                            .string()
                            .max(featureFlagsListResponseResultsItemLastModifiedByOneDistinctIdMax)
                            .nullish(),
                        first_name: zod
                            .string()
                            .max(featureFlagsListResponseResultsItemLastModifiedByOneFirstNameMax)
                            .optional(),
                        last_name: zod
                            .string()
                            .max(featureFlagsListResponseResultsItemLastModifiedByOneLastNameMax)
                            .optional(),
                        email: zod.string().email().max(featureFlagsListResponseResultsItemLastModifiedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
                    })
                    .optional(),
                ensure_experience_continuity: zod.boolean().nullish(),
                experiment_set: zod.array(zod.number()).optional(),
                surveys: zod.record(zod.string(), zod.unknown()).optional(),
                features: zod.record(zod.string(), zod.unknown()).optional(),
                rollback_conditions: zod.unknown().nullish(),
                performed_rollback: zod.boolean().nullish(),
                can_edit: zod.boolean().optional(),
                tags: zod.array(zod.unknown()).optional(),
                evaluation_tags: zod.array(zod.unknown()).optional(),
                usage_dashboard: zod.number().optional(),
                analytics_dashboards: zod.array(zod.number()).optional(),
                has_enriched_analytics: zod.boolean().nullish(),
                user_access_level: zod
                    .string()
                    .nullish()
                    .describe('The effective access level the user has for this object'),
                creation_context: zod
                    .enum([
                        'feature_flags',
                        'experiments',
                        'surveys',
                        'early_access_features',
                        'web_experiments',
                        'product_tours',
                    ])
                    .describe(
                        '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
                    )
                    .optional()
                    .describe(
                        "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
                    ),
                is_remote_configuration: zod.boolean().nullish(),
                has_encrypted_payloads: zod.boolean().nullish(),
                status: zod.string().optional(),
                evaluation_runtime: zod
                    .union([
                        zod
                            .enum(['server', 'client', 'all'])
                            .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                    ),
                bucketing_identifier: zod
                    .union([
                        zod
                            .enum(['distinct_id', 'device_id'])
                            .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                    ),
                last_called_at: zod
                    .string()
                    .datetime({})
                    .nullish()
                    .describe('Last time this feature flag was called (from $feature_flag_called events)'),
                _create_in_folder: zod.string().optional(),
                _should_create_usage_dashboard: zod
                    .boolean()
                    .default(featureFlagsListResponseResultsItemShouldCreateUsageDashboardDefault),
                is_used_in_replay_settings: zod
                    .boolean()
                    .optional()
                    .describe(
                        "Check if this feature flag is used in any team's session recording linked flag setting."
                    ),
            })
            .describe('Serializer mixin that handles tags for objects.')
    ),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const FeatureFlagsCreateBody = zod.object({
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
export const FeatureFlagsRetrieve2Params = zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsRetrieve2ResponseKeyMax = 400

export const featureFlagsRetrieve2ResponseCreatedByOneDistinctIdMax = 200

export const featureFlagsRetrieve2ResponseCreatedByOneFirstNameMax = 150

export const featureFlagsRetrieve2ResponseCreatedByOneLastNameMax = 150

export const featureFlagsRetrieve2ResponseCreatedByOneEmailMax = 254

export const featureFlagsRetrieve2ResponseVersionDefault = 0
export const featureFlagsRetrieve2ResponseLastModifiedByOneDistinctIdMax = 200

export const featureFlagsRetrieve2ResponseLastModifiedByOneFirstNameMax = 150

export const featureFlagsRetrieve2ResponseLastModifiedByOneLastNameMax = 150

export const featureFlagsRetrieve2ResponseLastModifiedByOneEmailMax = 254

export const featureFlagsRetrieve2ResponseShouldCreateUsageDashboardDefault = true

export const FeatureFlagsRetrieve2Response = zod
    .object({
        id: zod.number().optional(),
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsRetrieve2ResponseKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(featureFlagsRetrieve2ResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(featureFlagsRetrieve2ResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(featureFlagsRetrieve2ResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(featureFlagsRetrieve2ResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
            })
            .optional(),
        created_at: zod.string().datetime({}).optional(),
        updated_at: zod.string().datetime({}).nullish(),
        version: zod.number().default(featureFlagsRetrieve2ResponseVersionDefault),
        last_modified_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(featureFlagsRetrieve2ResponseLastModifiedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(featureFlagsRetrieve2ResponseLastModifiedByOneFirstNameMax).optional(),
                last_name: zod.string().max(featureFlagsRetrieve2ResponseLastModifiedByOneLastNameMax).optional(),
                email: zod.string().email().max(featureFlagsRetrieve2ResponseLastModifiedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
            })
            .optional(),
        ensure_experience_continuity: zod.boolean().nullish(),
        experiment_set: zod.array(zod.number()).optional(),
        surveys: zod.record(zod.string(), zod.unknown()).optional(),
        features: zod.record(zod.string(), zod.unknown()).optional(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        can_edit: zod.boolean().optional(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        usage_dashboard: zod.number().optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        status: zod.string().optional(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsRetrieve2ResponseShouldCreateUsageDashboardDefault),
        is_used_in_replay_settings: zod
            .boolean()
            .optional()
            .describe("Check if this feature flag is used in any team's session recording linked flag setting."),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsUpdateBodyKeyMax = 400

export const featureFlagsUpdateBodyVersionDefault = 0
export const featureFlagsUpdateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsUpdateBody = zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsUpdateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        version: zod.number().default(featureFlagsUpdateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod.boolean().default(featureFlagsUpdateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const featureFlagsUpdateResponseKeyMax = 400

export const featureFlagsUpdateResponseCreatedByOneDistinctIdMax = 200

export const featureFlagsUpdateResponseCreatedByOneFirstNameMax = 150

export const featureFlagsUpdateResponseCreatedByOneLastNameMax = 150

export const featureFlagsUpdateResponseCreatedByOneEmailMax = 254

export const featureFlagsUpdateResponseVersionDefault = 0
export const featureFlagsUpdateResponseLastModifiedByOneDistinctIdMax = 200

export const featureFlagsUpdateResponseLastModifiedByOneFirstNameMax = 150

export const featureFlagsUpdateResponseLastModifiedByOneLastNameMax = 150

export const featureFlagsUpdateResponseLastModifiedByOneEmailMax = 254

export const featureFlagsUpdateResponseShouldCreateUsageDashboardDefault = true

export const FeatureFlagsUpdateResponse = zod
    .object({
        id: zod.number().optional(),
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsUpdateResponseKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(featureFlagsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(featureFlagsUpdateResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(featureFlagsUpdateResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(featureFlagsUpdateResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
            })
            .optional(),
        created_at: zod.string().datetime({}).optional(),
        updated_at: zod.string().datetime({}).nullish(),
        version: zod.number().default(featureFlagsUpdateResponseVersionDefault),
        last_modified_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(featureFlagsUpdateResponseLastModifiedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(featureFlagsUpdateResponseLastModifiedByOneFirstNameMax).optional(),
                last_name: zod.string().max(featureFlagsUpdateResponseLastModifiedByOneLastNameMax).optional(),
                email: zod.string().email().max(featureFlagsUpdateResponseLastModifiedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
            })
            .optional(),
        ensure_experience_continuity: zod.boolean().nullish(),
        experiment_set: zod.array(zod.number()).optional(),
        surveys: zod.record(zod.string(), zod.unknown()).optional(),
        features: zod.record(zod.string(), zod.unknown()).optional(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        can_edit: zod.boolean().optional(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        usage_dashboard: zod.number().optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        status: zod.string().optional(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsUpdateResponseShouldCreateUsageDashboardDefault),
        is_used_in_replay_settings: zod
            .boolean()
            .optional()
            .describe("Check if this feature flag is used in any team's session recording linked flag setting."),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsPartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const FeatureFlagsPartialUpdateBody = zod.object({
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

export const featureFlagsPartialUpdateResponseKeyMax = 400

export const featureFlagsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const featureFlagsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const featureFlagsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const featureFlagsPartialUpdateResponseCreatedByOneEmailMax = 254

export const featureFlagsPartialUpdateResponseVersionDefault = 0
export const featureFlagsPartialUpdateResponseLastModifiedByOneDistinctIdMax = 200

export const featureFlagsPartialUpdateResponseLastModifiedByOneFirstNameMax = 150

export const featureFlagsPartialUpdateResponseLastModifiedByOneLastNameMax = 150

export const featureFlagsPartialUpdateResponseLastModifiedByOneEmailMax = 254

export const featureFlagsPartialUpdateResponseShouldCreateUsageDashboardDefault = true

export const FeatureFlagsPartialUpdateResponse = zod
    .object({
        id: zod.number().optional(),
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsPartialUpdateResponseKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(featureFlagsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(featureFlagsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(featureFlagsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(featureFlagsPartialUpdateResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
            })
            .optional(),
        created_at: zod.string().datetime({}).optional(),
        updated_at: zod.string().datetime({}).nullish(),
        version: zod.number().default(featureFlagsPartialUpdateResponseVersionDefault),
        last_modified_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod
                    .string()
                    .max(featureFlagsPartialUpdateResponseLastModifiedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod.string().max(featureFlagsPartialUpdateResponseLastModifiedByOneFirstNameMax).optional(),
                last_name: zod.string().max(featureFlagsPartialUpdateResponseLastModifiedByOneLastNameMax).optional(),
                email: zod.string().email().max(featureFlagsPartialUpdateResponseLastModifiedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
            })
            .optional(),
        ensure_experience_continuity: zod.boolean().nullish(),
        experiment_set: zod.array(zod.number()).optional(),
        surveys: zod.record(zod.string(), zod.unknown()).optional(),
        features: zod.record(zod.string(), zod.unknown()).optional(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        can_edit: zod.boolean().optional(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        usage_dashboard: zod.number().optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        status: zod.string().optional(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsPartialUpdateResponseShouldCreateUsageDashboardDefault),
        is_used_in_replay_settings: zod
            .boolean()
            .optional()
            .describe("Check if this feature flag is used in any team's session recording linked flag setting."),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const FeatureFlagsDestroyParams = zod.object({
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
export const FeatureFlagsCreateStaticCohortForFlagCreateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsCreateStaticCohortForFlagCreateBodyKeyMax = 400

export const featureFlagsCreateStaticCohortForFlagCreateBodyVersionDefault = 0
export const featureFlagsCreateStaticCohortForFlagCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsCreateStaticCohortForFlagCreateBody = zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsCreateStaticCohortForFlagCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        version: zod.number().default(featureFlagsCreateStaticCohortForFlagCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsCreateStaticCohortForFlagCreateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsDashboardCreateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsDashboardCreateBodyKeyMax = 400

export const featureFlagsDashboardCreateBodyVersionDefault = 0
export const featureFlagsDashboardCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsDashboardCreateBody = zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsDashboardCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        version: zod.number().default(featureFlagsDashboardCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsDashboardCreateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Get other active flags that depend on this flag.
 */
export const FeatureFlagsDependentFlagsRetrieveParams = zod.object({
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
export const FeatureFlagsEnrichUsageDashboardCreateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsEnrichUsageDashboardCreateBodyKeyMax = 400

export const featureFlagsEnrichUsageDashboardCreateBodyVersionDefault = 0
export const featureFlagsEnrichUsageDashboardCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsEnrichUsageDashboardCreateBody = zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsEnrichUsageDashboardCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        version: zod.number().default(featureFlagsEnrichUsageDashboardCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsEnrichUsageDashboardCreateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsRemoteConfigRetrieveParams = zod.object({
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
export const FeatureFlagsStatusRetrieveParams = zod.object({
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
export const FeatureFlagsActivityRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsActivityRetrieveQueryLimitDefault = 10

export const featureFlagsActivityRetrieveQueryPageDefault = 1

export const FeatureFlagsActivityRetrieveQueryParams = zod.object({
    limit: zod
        .number()
        .min(1)
        .default(featureFlagsActivityRetrieveQueryLimitDefault)
        .describe('Number of items per page'),
    page: zod.number().min(1).default(featureFlagsActivityRetrieveQueryPageDefault).describe('Page number'),
})

export const FeatureFlagsActivityRetrieveResponse = zod
    .object({
        results: zod.array(
            zod.object({
                user: zod.string().optional(),
                activity: zod.string().optional(),
                scope: zod.string().optional(),
                item_id: zod.string().optional(),
                detail: zod
                    .object({
                        id: zod.string().optional(),
                        changes: zod
                            .array(
                                zod.object({
                                    type: zod.string().optional(),
                                    action: zod.string().optional(),
                                    field: zod.string().optional(),
                                    before: zod.unknown().optional(),
                                    after: zod.unknown().optional(),
                                })
                            )
                            .optional(),
                        merge: zod
                            .object({
                                type: zod.string().optional(),
                                source: zod.unknown().optional(),
                                target: zod.unknown().optional(),
                            })
                            .optional(),
                        trigger: zod
                            .object({
                                job_type: zod.string().optional(),
                                job_id: zod.string().optional(),
                                payload: zod.unknown().optional(),
                            })
                            .optional(),
                        name: zod.string().optional(),
                        short_id: zod.string().optional(),
                        type: zod.string().optional(),
                    })
                    .optional(),
                created_at: zod.string().datetime({}).optional(),
            })
        ),
        next: zod.string().url().nullable(),
        previous: zod.string().url().nullable(),
        total_count: zod.number(),
    })
    .describe('Response shape for paginated activity log endpoints.')

/**
 * Bulk delete feature flags by filter criteria or explicit IDs.

Accepts either:
- {"filters": {...}} - Same filter params as list endpoint (search, active, type, etc.)
- {"ids": [...]} - Explicit list of flag IDs (no limit)

Returns same format as bulk_delete for UI compatibility.

Uses bulk operations for efficiency: database updates are batched and cache
invalidation happens once at the end rather than per-flag.
 */
export const FeatureFlagsBulkDeleteCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsBulkDeleteCreateBodyKeyMax = 400

export const featureFlagsBulkDeleteCreateBodyVersionDefault = 0
export const featureFlagsBulkDeleteCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsBulkDeleteCreateBody = zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsBulkDeleteCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        version: zod.number().default(featureFlagsBulkDeleteCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsBulkDeleteCreateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Get feature flag keys by IDs.
Accepts a list of feature flag IDs and returns a mapping of ID to key.
 */
export const FeatureFlagsBulkKeysCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsBulkKeysCreateBodyKeyMax = 400

export const featureFlagsBulkKeysCreateBodyVersionDefault = 0
export const featureFlagsBulkKeysCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsBulkKeysCreateBody = zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsBulkKeysCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        version: zod.number().default(featureFlagsBulkKeysCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsBulkKeysCreateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsEvaluationReasonsRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsEvaluationReasonsRetrieveQueryGroupsDefault = `{}`

export const FeatureFlagsEvaluationReasonsRetrieveQueryParams = zod.object({
    distinct_id: zod.string().min(1).describe('User distinct ID'),
    groups: zod
        .string()
        .default(featureFlagsEvaluationReasonsRetrieveQueryGroupsDefault)
        .describe('Groups for feature flag evaluation (JSON object string)'),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsLocalEvaluationRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsLocalEvaluationRetrieveQuerySendCohortsDefault = false

export const FeatureFlagsLocalEvaluationRetrieveQueryParams = zod.object({
    send_cohorts: zod
        .boolean()
        .default(featureFlagsLocalEvaluationRetrieveQuerySendCohortsDefault)
        .describe('Include cohorts in response'),
})

export const featureFlagsLocalEvaluationRetrieveResponseFlagsItemKeyMax = 400

export const featureFlagsLocalEvaluationRetrieveResponseFlagsItemVersionMin = -2147483648
export const featureFlagsLocalEvaluationRetrieveResponseFlagsItemVersionMax = 2147483647

export const FeatureFlagsLocalEvaluationRetrieveResponse = zod.object({
    flags: zod.array(
        zod.object({
            id: zod.number().optional(),
            team_id: zod.number().optional(),
            name: zod.string().optional(),
            key: zod.string().max(featureFlagsLocalEvaluationRetrieveResponseFlagsItemKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(featureFlagsLocalEvaluationRetrieveResponseFlagsItemVersionMin)
                .max(featureFlagsLocalEvaluationRetrieveResponseFlagsItemVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_tags: zod.array(zod.string()).optional(),
            evaluation_contexts: zod.array(zod.string()).optional(),
        })
    ),
    group_type_mapping: zod.record(zod.string(), zod.string()),
    cohorts: zod
        .record(zod.string(), zod.unknown())
        .describe(
            "Cohort definitions keyed by cohort ID. Each value is a property group structure with 'type' (OR/AND) and 'values' (array of property groups or property filters)."
        ),
})

/**
 * Get IDs of all feature flags matching the current filters.
Uses the same filtering logic as the list endpoint.
Returns only IDs that the user has permission to edit.
 */
export const FeatureFlagsMatchingIdsRetrieveParams = zod.object({
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
export const FeatureFlagsMyFlagsRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsMyFlagsRetrieveQueryGroupsDefault = `{}`

export const FeatureFlagsMyFlagsRetrieveQueryParams = zod.object({
    groups: zod
        .string()
        .default(featureFlagsMyFlagsRetrieveQueryGroupsDefault)
        .describe('Groups for feature flag evaluation (JSON object string)'),
})

export const featureFlagsMyFlagsRetrieveResponseFeatureFlagKeyMax = 400

export const featureFlagsMyFlagsRetrieveResponseFeatureFlagVersionMin = -2147483648
export const featureFlagsMyFlagsRetrieveResponseFeatureFlagVersionMax = 2147483647

export const FeatureFlagsMyFlagsRetrieveResponseItem = zod.object({
    feature_flag: zod.object({
        id: zod.number().optional(),
        team_id: zod.number().optional(),
        name: zod.string().optional(),
        key: zod.string().max(featureFlagsMyFlagsRetrieveResponseFeatureFlagKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        ensure_experience_continuity: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        version: zod
            .number()
            .min(featureFlagsMyFlagsRetrieveResponseFeatureFlagVersionMin)
            .max(featureFlagsMyFlagsRetrieveResponseFeatureFlagVersionMax)
            .nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        evaluation_tags: zod.array(zod.string()).optional(),
        evaluation_contexts: zod.array(zod.string()).optional(),
    }),
    value: zod.unknown(),
})
export const FeatureFlagsMyFlagsRetrieveResponse = zod.array(FeatureFlagsMyFlagsRetrieveResponseItem)

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsUserBlastRadiusCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const featureFlagsUserBlastRadiusCreateBodyKeyMax = 400

export const featureFlagsUserBlastRadiusCreateBodyVersionDefault = 0
export const featureFlagsUserBlastRadiusCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsUserBlastRadiusCreateBody = zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsUserBlastRadiusCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        version: zod.number().default(featureFlagsUserBlastRadiusCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_tags: zod.array(zod.unknown()).optional(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        creation_context: zod
            .enum([
                'feature_flags',
                'experiments',
                'surveys',
                'early_access_features',
                'web_experiments',
                'product_tours',
            ])
            .describe(
                '* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n* `feature_flags` - feature_flags\n* `experiments` - experiments\n* `surveys` - surveys\n* `early_access_features` - early_access_features\n* `web_experiments` - web_experiments\n* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        last_called_at: zod
            .string()
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsUserBlastRadiusCreateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')
