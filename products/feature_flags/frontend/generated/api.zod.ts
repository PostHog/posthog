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

export const featureFlagsCopyFlagsCreateBodyTargetProjectIdsMax = 50

export const featureFlagsCopyFlagsCreateBodyCopyScheduleDefault = false

export const FeatureFlagsCopyFlagsCreateBody = /* @__PURE__ */ zod.object({
    feature_flag_key: zod.string().describe('Key of the feature flag to copy'),
    from_project: zod.number().describe('Source project ID to copy the flag from'),
    target_project_ids: zod
        .array(zod.number())
        .max(featureFlagsCopyFlagsCreateBodyTargetProjectIdsMax)
        .describe('List of target project IDs to copy the flag to'),
    copy_schedule: zod
        .boolean()
        .default(featureFlagsCopyFlagsCreateBodyCopyScheduleDefault)
        .describe('Whether to also copy scheduled changes for this flag'),
})

export const FeatureFlagsCopyFlagsCreateResponse = /* @__PURE__ */ zod.object({
    success: zod
        .array(
            zod.object({
                id: zod.number().describe('ID of the created feature flag'),
                key: zod.string().describe('Key of the feature flag'),
                name: zod.string().describe('Name of the feature flag'),
                active: zod.boolean().describe('Whether the flag is active'),
                team_id: zod.number().describe('Team ID the flag was copied to'),
            })
        )
        .describe('List of successfully copied flags'),
    failed: zod
        .array(
            zod.object({
                project_id: zod.number().optional().describe('Project ID (present on failure)'),
                error_message: zod.string().optional().describe('Error message (present on failure)'),
            })
        )
        .describe('List of failed copy attempts'),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const FeatureFlagsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number(),
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
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(featureFlagsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(featureFlagsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod.string().max(featureFlagsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.email().max(featureFlagsListResponseResultsItemCreatedByOneEmailMax),
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
                created_at: zod.iso.datetime({}).optional(),
                updated_at: zod.iso.datetime({}).nullable(),
                version: zod.number().default(featureFlagsListResponseResultsItemVersionDefault),
                last_modified_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
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
                    email: zod.email().max(featureFlagsListResponseResultsItemLastModifiedByOneEmailMax),
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
                ensure_experience_continuity: zod.boolean().nullish(),
                experiment_set: zod.array(zod.number()),
                experiment_set_metadata: zod.array(zod.record(zod.string(), zod.unknown())),
                surveys: zod.record(zod.string(), zod.unknown()),
                features: zod.record(zod.string(), zod.unknown()),
                rollback_conditions: zod.unknown().nullish(),
                performed_rollback: zod.boolean().nullish(),
                can_edit: zod.boolean(),
                tags: zod.array(zod.unknown()).optional(),
                evaluation_contexts: zod.array(zod.unknown()).optional(),
                usage_dashboard: zod.number(),
                analytics_dashboards: zod.array(zod.number()).optional(),
                has_enriched_analytics: zod.boolean().nullish(),
                user_access_level: zod
                    .string()
                    .nullable()
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
                status: zod.string(),
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
                last_called_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe('Last time this feature flag was called (from $feature_flag_called events)'),
                _create_in_folder: zod.string().optional(),
                _should_create_usage_dashboard: zod
                    .boolean()
                    .default(featureFlagsListResponseResultsItemShouldCreateUsageDashboardDefault),
                is_used_in_replay_settings: zod
                    .boolean()
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
            feature_enrollment: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment/{flag_key}.'
                ),
        })
        .optional()
        .describe('Feature flag targeting configuration.'),
    active: zod.boolean().optional().describe('Whether the feature flag is active.'),
    tags: zod.array(zod.string()).optional().describe('Organizational tags for this feature flag.'),
    evaluation_contexts: zod
        .array(zod.string())
        .optional()
        .describe('Evaluation contexts that control where this flag evaluates at runtime.'),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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

export const FeatureFlagsRetrieve2Response = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsRetrieve2ResponseKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(featureFlagsRetrieve2ResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(featureFlagsRetrieve2ResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(featureFlagsRetrieve2ResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(featureFlagsRetrieve2ResponseCreatedByOneEmailMax),
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
        created_at: zod.iso.datetime({}).optional(),
        updated_at: zod.iso.datetime({}).nullable(),
        version: zod.number().default(featureFlagsRetrieve2ResponseVersionDefault),
        last_modified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(featureFlagsRetrieve2ResponseLastModifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(featureFlagsRetrieve2ResponseLastModifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(featureFlagsRetrieve2ResponseLastModifiedByOneLastNameMax).optional(),
            email: zod.email().max(featureFlagsRetrieve2ResponseLastModifiedByOneEmailMax),
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
        ensure_experience_continuity: zod.boolean().nullish(),
        experiment_set: zod.array(zod.number()),
        experiment_set_metadata: zod.array(zod.record(zod.string(), zod.unknown())),
        surveys: zod.record(zod.string(), zod.unknown()),
        features: zod.record(zod.string(), zod.unknown()),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        can_edit: zod.boolean(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
        usage_dashboard: zod.number(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
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
        status: zod.string(),
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
        last_called_at: zod.iso
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsRetrieve2ResponseShouldCreateUsageDashboardDefault),
        is_used_in_replay_settings: zod
            .boolean()
            .describe("Check if this feature flag is used in any team's session recording linked flag setting."),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const featureFlagsUpdateBodyKeyMax = 400

export const featureFlagsUpdateBodyVersionDefault = 0
export const featureFlagsUpdateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsUpdateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.iso.datetime({}).optional(),
        version: zod.number().default(featureFlagsUpdateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
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
        last_called_at: zod.iso
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

export const FeatureFlagsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsUpdateResponseKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(featureFlagsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(featureFlagsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(featureFlagsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(featureFlagsUpdateResponseCreatedByOneEmailMax),
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
        created_at: zod.iso.datetime({}).optional(),
        updated_at: zod.iso.datetime({}).nullable(),
        version: zod.number().default(featureFlagsUpdateResponseVersionDefault),
        last_modified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(featureFlagsUpdateResponseLastModifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(featureFlagsUpdateResponseLastModifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(featureFlagsUpdateResponseLastModifiedByOneLastNameMax).optional(),
            email: zod.email().max(featureFlagsUpdateResponseLastModifiedByOneEmailMax),
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
        ensure_experience_continuity: zod.boolean().nullish(),
        experiment_set: zod.array(zod.number()),
        experiment_set_metadata: zod.array(zod.record(zod.string(), zod.unknown())),
        surveys: zod.record(zod.string(), zod.unknown()),
        features: zod.record(zod.string(), zod.unknown()),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        can_edit: zod.boolean(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
        usage_dashboard: zod.number(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
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
        status: zod.string(),
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
        last_called_at: zod.iso
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsUpdateResponseShouldCreateUsageDashboardDefault),
        is_used_in_replay_settings: zod
            .boolean()
            .describe("Check if this feature flag is used in any team's session recording linked flag setting."),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
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
            feature_enrollment: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment/{flag_key}.'
                ),
        })
        .optional()
        .describe('Feature flag targeting configuration.'),
    active: zod.boolean().optional().describe('Whether the feature flag is active.'),
    tags: zod.array(zod.string()).optional().describe('Organizational tags for this feature flag.'),
    evaluation_contexts: zod
        .array(zod.string())
        .optional()
        .describe('Evaluation contexts that control where this flag evaluates at runtime.'),
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

export const FeatureFlagsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsPartialUpdateResponseKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(featureFlagsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(featureFlagsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(featureFlagsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(featureFlagsPartialUpdateResponseCreatedByOneEmailMax),
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
        created_at: zod.iso.datetime({}).optional(),
        updated_at: zod.iso.datetime({}).nullable(),
        version: zod.number().default(featureFlagsPartialUpdateResponseVersionDefault),
        last_modified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(featureFlagsPartialUpdateResponseLastModifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(featureFlagsPartialUpdateResponseLastModifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(featureFlagsPartialUpdateResponseLastModifiedByOneLastNameMax).optional(),
            email: zod.email().max(featureFlagsPartialUpdateResponseLastModifiedByOneEmailMax),
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
        ensure_experience_continuity: zod.boolean().nullish(),
        experiment_set: zod.array(zod.number()),
        experiment_set_metadata: zod.array(zod.record(zod.string(), zod.unknown())),
        surveys: zod.record(zod.string(), zod.unknown()),
        features: zod.record(zod.string(), zod.unknown()),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        can_edit: zod.boolean(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
        usage_dashboard: zod.number(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
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
        status: zod.string(),
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
        last_called_at: zod.iso
            .datetime({})
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsPartialUpdateResponseShouldCreateUsageDashboardDefault),
        is_used_in_replay_settings: zod
            .boolean()
            .describe("Check if this feature flag is used in any team's session recording linked flag setting."),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsActivityRetrieve2Response = /* @__PURE__ */ zod
    .object({
        results: zod.array(
            zod.object({
                id: zod.uuid(),
                user: zod.object({}).nullable(),
                activity: zod.string(),
                scope: zod.string(),
                item_id: zod.string(),
                detail: zod
                    .object({
                        id: zod.string(),
                        changes: zod
                            .array(
                                zod.object({
                                    type: zod.string(),
                                    action: zod.string(),
                                    field: zod.string(),
                                    before: zod.unknown(),
                                    after: zod.unknown(),
                                })
                            )
                            .optional(),
                        merge: zod
                            .object({
                                type: zod.string(),
                                source: zod.unknown(),
                                target: zod.unknown(),
                            })
                            .optional(),
                        trigger: zod
                            .object({
                                job_type: zod.string(),
                                job_id: zod.string(),
                                payload: zod.unknown(),
                            })
                            .optional(),
                        name: zod.string(),
                        short_id: zod.string(),
                        type: zod.string(),
                    })
                    .optional(),
                created_at: zod.iso.datetime({}),
            })
        ),
        next: zod.url().nullable(),
        previous: zod.url().nullable(),
        total_count: zod.number(),
    })
    .describe('Response shape for paginated activity log endpoints.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const featureFlagsCreateStaticCohortForFlagCreateBodyKeyMax = 400

export const featureFlagsCreateStaticCohortForFlagCreateBodyVersionDefault = 0
export const featureFlagsCreateStaticCohortForFlagCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsCreateStaticCohortForFlagCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsCreateStaticCohortForFlagCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.iso.datetime({}).optional(),
        version: zod.number().default(featureFlagsCreateStaticCohortForFlagCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
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
        last_called_at: zod.iso
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
export const featureFlagsDashboardCreateBodyKeyMax = 400

export const featureFlagsDashboardCreateBodyVersionDefault = 0
export const featureFlagsDashboardCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsDashboardCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsDashboardCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.iso.datetime({}).optional(),
        version: zod.number().default(featureFlagsDashboardCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
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
        last_called_at: zod.iso
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
export const FeatureFlagsDependentFlagsListResponseItem = /* @__PURE__ */ zod.object({
    id: zod.number().describe('Feature flag ID'),
    key: zod.string().describe('Feature flag key'),
    name: zod.string().describe('Feature flag name'),
})
export const FeatureFlagsDependentFlagsListResponse = /* @__PURE__ */ zod.array(
    FeatureFlagsDependentFlagsListResponseItem
)

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const featureFlagsEnrichUsageDashboardCreateBodyKeyMax = 400

export const featureFlagsEnrichUsageDashboardCreateBodyVersionDefault = 0
export const featureFlagsEnrichUsageDashboardCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsEnrichUsageDashboardCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsEnrichUsageDashboardCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.iso.datetime({}).optional(),
        version: zod.number().default(featureFlagsEnrichUsageDashboardCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
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
        last_called_at: zod.iso
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
export const FeatureFlagsStatusRetrieveResponse = /* @__PURE__ */ zod.object({
    status: zod.string().describe('Flag status: active, stale, deleted, or unknown'),
    reason: zod.string().describe('Human-readable explanation of the status'),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsActivityRetrieveResponse = /* @__PURE__ */ zod
    .object({
        results: zod.array(
            zod.object({
                id: zod.uuid(),
                user: zod.object({}).nullable(),
                activity: zod.string(),
                scope: zod.string(),
                item_id: zod.string(),
                detail: zod
                    .object({
                        id: zod.string(),
                        changes: zod
                            .array(
                                zod.object({
                                    type: zod.string(),
                                    action: zod.string(),
                                    field: zod.string(),
                                    before: zod.unknown(),
                                    after: zod.unknown(),
                                })
                            )
                            .optional(),
                        merge: zod
                            .object({
                                type: zod.string(),
                                source: zod.unknown(),
                                target: zod.unknown(),
                            })
                            .optional(),
                        trigger: zod
                            .object({
                                job_type: zod.string(),
                                job_id: zod.string(),
                                payload: zod.unknown(),
                            })
                            .optional(),
                        name: zod.string(),
                        short_id: zod.string(),
                        type: zod.string(),
                    })
                    .optional(),
                created_at: zod.iso.datetime({}),
            })
        ),
        next: zod.url().nullable(),
        previous: zod.url().nullable(),
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
export const featureFlagsBulkDeleteCreateBodyKeyMax = 400

export const featureFlagsBulkDeleteCreateBodyVersionDefault = 0
export const featureFlagsBulkDeleteCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsBulkDeleteCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsBulkDeleteCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.iso.datetime({}).optional(),
        version: zod.number().default(featureFlagsBulkDeleteCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
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
        last_called_at: zod.iso
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
export const featureFlagsBulkKeysCreateBodyKeyMax = 400

export const featureFlagsBulkKeysCreateBodyVersionDefault = 0
export const featureFlagsBulkKeysCreateBodyShouldCreateUsageDashboardDefault = true

export const FeatureFlagsBulkKeysCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagsBulkKeysCreateBodyKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        created_at: zod.iso.datetime({}).optional(),
        version: zod.number().default(featureFlagsBulkKeysCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().nullish(),
        performed_rollback: zod.boolean().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
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
        last_called_at: zod.iso
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
export const featureFlagsLocalEvaluationRetrieveResponseFlagsItemKeyMax = 400

export const featureFlagsLocalEvaluationRetrieveResponseFlagsItemVersionMin = -2147483648
export const featureFlagsLocalEvaluationRetrieveResponseFlagsItemVersionMax = 2147483647

export const FeatureFlagsLocalEvaluationRetrieveResponse = /* @__PURE__ */ zod.object({
    flags: zod.array(
        zod.object({
            id: zod.number(),
            team_id: zod.number(),
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
            evaluation_contexts: zod.array(zod.string()),
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
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const featureFlagsMyFlagsRetrieveResponseFeatureFlagKeyMax = 400

export const featureFlagsMyFlagsRetrieveResponseFeatureFlagVersionMin = -2147483648
export const featureFlagsMyFlagsRetrieveResponseFeatureFlagVersionMax = 2147483647

export const FeatureFlagsMyFlagsRetrieveResponseItem = /* @__PURE__ */ zod.object({
    feature_flag: zod.object({
        id: zod.number(),
        team_id: zod.number(),
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
        evaluation_contexts: zod.array(zod.string()),
    }),
    value: zod.unknown(),
})
export const FeatureFlagsMyFlagsRetrieveResponse = /* @__PURE__ */ zod.array(FeatureFlagsMyFlagsRetrieveResponseItem)

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsUserBlastRadiusCreateBody = /* @__PURE__ */ zod.object({
    condition: zod.record(zod.string(), zod.unknown()).describe('The release condition to evaluate'),
    group_type_index: zod
        .number()
        .nullish()
        .describe('Group type index for group-based flags (null for person-based flags)'),
})

export const FeatureFlagsUserBlastRadiusCreateResponse = /* @__PURE__ */ zod.object({
    affected: zod
        .number()
        .describe('Number of entities matching the condition (users or groups depending on group_type_index)'),
    total: zod.number().describe('Total number of entities of this type in the project'),
})

/**
 * Create, read, update and delete scheduled changes.
 */
export const scheduledChangesListResponseResultsItemRecordIdMax = 200

export const scheduledChangesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const scheduledChangesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const scheduledChangesListResponseResultsItemCreatedByOneLastNameMax = 150

export const scheduledChangesListResponseResultsItemCreatedByOneEmailMax = 254

export const scheduledChangesListResponseResultsItemIsRecurringDefault = false
export const scheduledChangesListResponseResultsItemCronExpressionMax = 100

export const ScheduledChangesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.number(),
            team_id: zod.number(),
            record_id: zod
                .string()
                .max(scheduledChangesListResponseResultsItemRecordIdMax)
                .describe('The ID of the record to modify (e.g. the feature flag ID).'),
            model_name: zod
                .enum(['FeatureFlag'])
                .describe('* `FeatureFlag` - feature flag')
                .describe(
                    'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n* `FeatureFlag` - feature flag'
                ),
            payload: zod
                .unknown()
                .describe(
                    "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
                ),
            scheduled_at: zod.iso
                .datetime({})
                .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
            executed_at: zod.iso.datetime({}).nullish(),
            failure_reason: zod
                .string()
                .nullable()
                .describe('Return the safely formatted failure reason instead of raw data.'),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(scheduledChangesListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(scheduledChangesListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod.string().max(scheduledChangesListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(scheduledChangesListResponseResultsItemCreatedByOneEmailMax),
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
            updated_at: zod.iso.datetime({}),
            is_recurring: zod
                .boolean()
                .default(scheduledChangesListResponseResultsItemIsRecurringDefault)
                .describe(
                    "Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."
                ),
            recurrence_interval: zod
                .union([
                    zod
                        .enum(['daily', 'weekly', 'monthly', 'yearly'])
                        .describe('* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'
                ),
            cron_expression: zod.string().max(scheduledChangesListResponseResultsItemCronExpressionMax).nullish(),
            last_executed_at: zod.iso.datetime({}).nullable(),
            end_date: zod.iso
                .datetime({})
                .nullish()
                .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
        })
    ),
})

/**
 * Create, read, update and delete scheduled changes.
 */
export const scheduledChangesCreateBodyRecordIdMax = 200

export const scheduledChangesCreateBodyIsRecurringDefault = false
export const scheduledChangesCreateBodyCronExpressionMax = 100

export const ScheduledChangesCreateBody = /* @__PURE__ */ zod.object({
    record_id: zod
        .string()
        .max(scheduledChangesCreateBodyRecordIdMax)
        .describe('The ID of the record to modify (e.g. the feature flag ID).'),
    model_name: zod
        .enum(['FeatureFlag'])
        .describe('* `FeatureFlag` - feature flag')
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({})
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    executed_at: zod.iso.datetime({}).nullish(),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesCreateBodyIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesCreateBodyCronExpressionMax).nullish(),
    end_date: zod.iso
        .datetime({})
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
})

/**
 * Create, read, update and delete scheduled changes.
 */
export const scheduledChangesRetrieveResponseRecordIdMax = 200

export const scheduledChangesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const scheduledChangesRetrieveResponseCreatedByOneFirstNameMax = 150

export const scheduledChangesRetrieveResponseCreatedByOneLastNameMax = 150

export const scheduledChangesRetrieveResponseCreatedByOneEmailMax = 254

export const scheduledChangesRetrieveResponseIsRecurringDefault = false
export const scheduledChangesRetrieveResponseCronExpressionMax = 100

export const ScheduledChangesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    team_id: zod.number(),
    record_id: zod
        .string()
        .max(scheduledChangesRetrieveResponseRecordIdMax)
        .describe('The ID of the record to modify (e.g. the feature flag ID).'),
    model_name: zod
        .enum(['FeatureFlag'])
        .describe('* `FeatureFlag` - feature flag')
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({})
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    executed_at: zod.iso.datetime({}).nullish(),
    failure_reason: zod.string().nullable().describe('Return the safely formatted failure reason instead of raw data.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(scheduledChangesRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(scheduledChangesRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(scheduledChangesRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(scheduledChangesRetrieveResponseCreatedByOneEmailMax),
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
    updated_at: zod.iso.datetime({}),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesRetrieveResponseIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesRetrieveResponseCronExpressionMax).nullish(),
    last_executed_at: zod.iso.datetime({}).nullable(),
    end_date: zod.iso
        .datetime({})
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
})

/**
 * Create, read, update and delete scheduled changes.
 */
export const scheduledChangesUpdateBodyRecordIdMax = 200

export const scheduledChangesUpdateBodyIsRecurringDefault = false
export const scheduledChangesUpdateBodyCronExpressionMax = 100

export const ScheduledChangesUpdateBody = /* @__PURE__ */ zod.object({
    record_id: zod
        .string()
        .max(scheduledChangesUpdateBodyRecordIdMax)
        .describe('The ID of the record to modify (e.g. the feature flag ID).'),
    model_name: zod
        .enum(['FeatureFlag'])
        .describe('* `FeatureFlag` - feature flag')
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({})
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    executed_at: zod.iso.datetime({}).nullish(),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesUpdateBodyIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesUpdateBodyCronExpressionMax).nullish(),
    end_date: zod.iso
        .datetime({})
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
})

export const scheduledChangesUpdateResponseRecordIdMax = 200

export const scheduledChangesUpdateResponseCreatedByOneDistinctIdMax = 200

export const scheduledChangesUpdateResponseCreatedByOneFirstNameMax = 150

export const scheduledChangesUpdateResponseCreatedByOneLastNameMax = 150

export const scheduledChangesUpdateResponseCreatedByOneEmailMax = 254

export const scheduledChangesUpdateResponseIsRecurringDefault = false
export const scheduledChangesUpdateResponseCronExpressionMax = 100

export const ScheduledChangesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    team_id: zod.number(),
    record_id: zod
        .string()
        .max(scheduledChangesUpdateResponseRecordIdMax)
        .describe('The ID of the record to modify (e.g. the feature flag ID).'),
    model_name: zod
        .enum(['FeatureFlag'])
        .describe('* `FeatureFlag` - feature flag')
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({})
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    executed_at: zod.iso.datetime({}).nullish(),
    failure_reason: zod.string().nullable().describe('Return the safely formatted failure reason instead of raw data.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(scheduledChangesUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(scheduledChangesUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(scheduledChangesUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(scheduledChangesUpdateResponseCreatedByOneEmailMax),
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
    updated_at: zod.iso.datetime({}),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesUpdateResponseIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesUpdateResponseCronExpressionMax).nullish(),
    last_executed_at: zod.iso.datetime({}).nullable(),
    end_date: zod.iso
        .datetime({})
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
})

/**
 * Create, read, update and delete scheduled changes.
 */
export const scheduledChangesPartialUpdateBodyRecordIdMax = 200

export const scheduledChangesPartialUpdateBodyIsRecurringDefault = false
export const scheduledChangesPartialUpdateBodyCronExpressionMax = 100

export const ScheduledChangesPartialUpdateBody = /* @__PURE__ */ zod.object({
    record_id: zod
        .string()
        .max(scheduledChangesPartialUpdateBodyRecordIdMax)
        .optional()
        .describe('The ID of the record to modify (e.g. the feature flag ID).'),
    model_name: zod
        .enum(['FeatureFlag'])
        .describe('* `FeatureFlag` - feature flag')
        .optional()
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .optional()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({})
        .optional()
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    executed_at: zod.iso.datetime({}).nullish(),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesPartialUpdateBodyIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesPartialUpdateBodyCronExpressionMax).nullish(),
    end_date: zod.iso
        .datetime({})
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
})

export const scheduledChangesPartialUpdateResponseRecordIdMax = 200

export const scheduledChangesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const scheduledChangesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const scheduledChangesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const scheduledChangesPartialUpdateResponseCreatedByOneEmailMax = 254

export const scheduledChangesPartialUpdateResponseIsRecurringDefault = false
export const scheduledChangesPartialUpdateResponseCronExpressionMax = 100

export const ScheduledChangesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    team_id: zod.number(),
    record_id: zod
        .string()
        .max(scheduledChangesPartialUpdateResponseRecordIdMax)
        .describe('The ID of the record to modify (e.g. the feature flag ID).'),
    model_name: zod
        .enum(['FeatureFlag'])
        .describe('* `FeatureFlag` - feature flag')
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({})
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    executed_at: zod.iso.datetime({}).nullish(),
    failure_reason: zod.string().nullable().describe('Return the safely formatted failure reason instead of raw data.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(scheduledChangesPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(scheduledChangesPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(scheduledChangesPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(scheduledChangesPartialUpdateResponseCreatedByOneEmailMax),
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
    updated_at: zod.iso.datetime({}),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesPartialUpdateResponseIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly\n* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesPartialUpdateResponseCronExpressionMax).nullish(),
    last_executed_at: zod.iso.datetime({}).nullable(),
    end_date: zod.iso
        .datetime({})
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
})
