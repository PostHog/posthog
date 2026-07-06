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
 * Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.
 *
 * Rebuild/clear act on two logical targets ('evaluation' and 'definitions'; the latter rebuilds
 * or clears both definitions-cache variants together). Status/entry can read a third, narrower
 * target ('definitions_no_cohorts') independently, since the two definitions-cache variants are
 * individually readable even though they're only mutated as a pair.
 *
 * Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
 * when a flag changes) rather than re-implementing cache-write logic. Registered on the root
 * router so it is not team-nested; staff act on teams they do not belong to.
 */
export const featureFlagsStaffCacheClearCreateBodyTeamIdsMax = 50

export const FeatureFlagsStaffCacheClearCreateBody = /* @__PURE__ */ zod.object({
    team_ids: zod
        .array(zod.number())
        .max(featureFlagsStaffCacheClearCreateBodyTeamIdsMax)
        .describe('Team ids to act on (max 50 per request).'),
    caches: zod
        .array(
            zod
                .enum(['evaluation', 'definitions'])
                .describe('\* `evaluation` - evaluation\n\* `definitions` - definitions')
        )
        .default([`evaluation`, `definitions`])
        .describe(
            "Which logical caches to act on: 'evaluation' (the \/flags cache) and\/or 'definitions' (the \/flags\/definitions local-eval cache). Defaults to both."
        ),
})

/**
 * Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.
 *
 * Rebuild/clear act on two logical targets ('evaluation' and 'definitions'; the latter rebuilds
 * or clears both definitions-cache variants together). Status/entry can read a third, narrower
 * target ('definitions_no_cohorts') independently, since the two definitions-cache variants are
 * individually readable even though they're only mutated as a pair.
 *
 * Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
 * when a flag changes) rather than re-implementing cache-write logic. Registered on the root
 * router so it is not team-nested; staff act on teams they do not belong to.
 */
export const featureFlagsStaffCacheRebuildCreateBodyTeamIdsMax = 50

export const FeatureFlagsStaffCacheRebuildCreateBody = /* @__PURE__ */ zod.object({
    team_ids: zod
        .array(zod.number())
        .max(featureFlagsStaffCacheRebuildCreateBodyTeamIdsMax)
        .describe('Team ids to act on (max 50 per request).'),
    caches: zod
        .array(
            zod
                .enum(['evaluation', 'definitions'])
                .describe('\* `evaluation` - evaluation\n\* `definitions` - definitions')
        )
        .default([`evaluation`, `definitions`])
        .describe(
            "Which logical caches to act on: 'evaluation' (the \/flags cache) and\/or 'definitions' (the \/flags\/definitions local-eval cache). Defaults to both."
        ),
})

export const featureFlagsCopyFlagsCreateBodyTargetProjectIdsMax = 50

export const featureFlagsCopyFlagsCreateBodyCopyScheduleDefault = false
export const featureFlagsCopyFlagsCreateBodyDisableCopiedFlagDefault = false
export const featureFlagsCopyFlagsCreateBodyCopyDependenciesDefault = false

export const FeatureFlagsCopyFlagsCreateBody = /* @__PURE__ */ zod.object({
    feature_flag_key: zod.string().describe('Key of the feature flag to copy'),
    from_project: zod.number().describe('Source project ID to copy the flag from'),
    target_project_ids: zod
        .array(zod.number())
        .min(1)
        .max(featureFlagsCopyFlagsCreateBodyTargetProjectIdsMax)
        .describe('List of target project IDs to copy the flag to'),
    copy_schedule: zod
        .boolean()
        .default(featureFlagsCopyFlagsCreateBodyCopyScheduleDefault)
        .describe('Whether to also copy scheduled changes for this flag'),
    disable_copied_flag: zod
        .boolean()
        .default(featureFlagsCopyFlagsCreateBodyDisableCopiedFlagDefault)
        .describe(
            "Whether to force the copied flag to be disabled in target projects, ignoring the source flag's enabled status"
        ),
    copy_dependencies: zod
        .boolean()
        .default(featureFlagsCopyFlagsCreateBodyCopyDependenciesDefault)
        .describe('Whether to also copy missing feature flags that this flag depends on'),
})

export const featureFlagsCopyFlagsDependencyRequirementsCreateBodyTargetProjectIdsMax = 50

export const FeatureFlagsCopyFlagsDependencyRequirementsCreateBody = /* @__PURE__ */ zod.object({
    feature_flag_key: zod.string().describe('Key of the feature flag to check'),
    from_project: zod.number().describe('Source project ID to copy the flag from'),
    target_project_ids: zod
        .array(zod.number())
        .min(1)
        .max(featureFlagsCopyFlagsDependencyRequirementsCreateBodyTargetProjectIdsMax)
        .describe('List of target project IDs to check dependency copy eligibility for'),
})

/**
 * Hide an evaluation context name from the flag editor's suggestion list, or restore it.
 *
 * POST hides the name; DELETE restores it. The underlying context row and any flags already
 * using it are never modified — this only controls what gets suggested.
 */
export const organizationsProjectsEvaluationContextSuggestionsCreateBodyContextNameMax = 255

export const OrganizationsProjectsEvaluationContextSuggestionsCreateBody = /* @__PURE__ */ zod.object({
    context_name: zod
        .string()
        .max(organizationsProjectsEvaluationContextSuggestionsCreateBodyContextNameMax)
        .describe(
            "Name of the evaluation context to hide from (POST) or restore to (DELETE) the flag editor's suggestion list. Case-insensitive and whitespace-trimmed."
        ),
})

/**
 * Hide an evaluation context name from the flag editor's suggestion list, or restore it.
 *
 * POST hides the name; DELETE restores it. The underlying context row and any flags already
 * using it are never modified — this only controls what gets suggested.
 */
export const environmentsEvaluationContextSuggestionsCreateBodyContextNameMax = 255

export const EnvironmentsEvaluationContextSuggestionsCreateBody = /* @__PURE__ */ zod.object({
    context_name: zod
        .string()
        .max(environmentsEvaluationContextSuggestionsCreateBodyContextNameMax)
        .describe(
            "Name of the evaluation context to hide from (POST) or restore to (DELETE) the flag editor's suggestion list. Case-insensitive and whitespace-trimmed."
        ),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const featureFlagsCreateBodyFiltersOneEarlyExitDefault = false

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
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `gte` - gte\n\* `lt` - lt\n\* `lte` - lte'
                                            )
                                            .describe(
                                                'Operator used to compare the property value.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `gte` - gte\n\* `lt` - lt\n\* `lte` - lte'
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                            .describe('\* `is_set` - is_set\n\* `is_not_set` - is_not_set')
                                            .describe(
                                                'Existence operator.\n\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
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
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                            .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
                                            .describe(
                                                '\* `is_date_exact` - is_date_exact\n\* `is_date_before` - is_date_before\n\* `is_date_after` - is_date_after'
                                            )
                                            .describe(
                                                'Date comparison operator.\n\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before'
                                            ),
                                        value: zod
                                            .string()
                                            .describe('Date value in ISO format or relative date expression.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                                '\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_eq` - semver_eq\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_caret` - semver_caret\n\* `semver_wildcard` - semver_wildcard'
                                            )
                                            .describe(
                                                'Semantic version comparison operator.\n\n\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_eq` - semver_eq\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_caret` - semver_caret\n\* `semver_wildcard` - semver_wildcard'
                                            ),
                                        value: zod.string().describe('Semantic version string.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                                '\* `icontains_multi` - icontains_multi\n\* `not_icontains_multi` - not_icontains_multi'
                                            )
                                            .describe(
                                                'Multi-contains operator.\n\n\* `icontains_multi` - icontains_multi\n\* `not_icontains_multi` - not_icontains_multi'
                                            ),
                                        value: zod.array(zod.string()).describe('List of strings to evaluate against.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort'])
                                            .describe('\* `cohort` - cohort')
                                            .describe(
                                                'Cohort property type required for in\/not_in operators.\n\n\* `cohort` - cohort'
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
                                            .describe('\* `in` - in\n\* `not_in` - not_in')
                                            .describe(
                                                'Membership operator for cohort properties.\n\n\* `in` - in\n\* `not_in` - not_in'
                                            ),
                                        value: zod
                                            .unknown()
                                            .describe('Cohort comparison value (single or list, depending on usage).'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['flag'])
                                            .describe('\* `flag` - flag')
                                            .describe(
                                                'Flag property type required for flag dependency checks.\n\n\* `flag` - flag'
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
                                            .describe('\* `flag_evaluates_to` - flag_evaluates_to')
                                            .describe(
                                                'Operator for feature flag dependency evaluation.\n\n\* `flag_evaluates_to` - flag_evaluates_to'
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
                .union([
                    zod.object({
                        variants: zod
                            .array(
                                zod.object({
                                    key: zod.string().describe('Unique key for this variant.'),
                                    name: zod.string().optional().describe('Human-readable name for this variant.'),
                                    rollout_percentage: zod.number().describe('Variant rollout percentage.'),
                                })
                            )
                            .describe('Variant definitions for multivariate feature flags.'),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe('Multivariate configuration for variant-based rollouts.'),
            aggregation_group_type_index: zod
                .number()
                .nullish()
                .describe('Group type index for group-based feature flags.'),
            payloads: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe('Optional payload values keyed by variant key.'),
            feature_enrollment: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment\/{flag_key}.'
                ),
            early_exit: zod
                .boolean()
                .default(featureFlagsCreateBodyFiltersOneEarlyExitDefault)
                .describe(
                    'When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups.'
                ),
        })
        .optional()
        .describe('Feature flag targeting configuration.'),
    active: zod.boolean().optional().describe('Whether the feature flag is active.'),
    archived: zod
        .boolean()
        .optional()
        .describe(
            'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
        ),
    tags: zod.array(zod.string()).optional().describe('Organizational tags for this feature flag.'),
    evaluation_contexts: zod
        .array(zod.string())
        .optional()
        .describe('Evaluation contexts that control where this flag evaluates at runtime.'),
    is_remote_configuration: zod
        .boolean()
        .nullish()
        .describe(
            'Whether this flag is a remote configuration flag that delivers a payload rather than gating a feature.'
        ),
    ensure_experience_continuity: zod
        .boolean()
        .nullish()
        .describe(
            "Whether to persist a user's flag value across the anonymous-to-identified transition (the 'persist across authentication steps' option). Incompatible with device_id bucketing."
        ),
    evaluation_runtime: zod
        .union([
            zod
                .enum(['server', 'client', 'all'])
                .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All'),
            zod.null(),
        ])
        .optional()
        .describe(
            "Where this flag is allowed to evaluate: 'server' (server-side SDKs only), 'client' (client-side SDKs only), or 'all' (both). Defaults to 'all'.\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All"
        ),
    bucketing_identifier: zod
        .union([
            zod
                .enum(['distinct_id', 'device_id'])
                .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'),
            zod.null(),
        ])
        .optional()
        .describe(
            "Identifier used to bucket users into rollout percentages and variants: 'distinct_id' (user ID, the default) or 'device_id'. Using 'device_id' is incompatible with ensure_experience_continuity=True.\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID"
        ),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
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
        archived: zod
            .boolean()
            .optional()
            .describe(
                'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        version: zod.number().default(featureFlagsUpdateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().optional(),
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
                '\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
            ),
        last_called_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod.boolean().default(featureFlagsUpdateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const featureFlagsPartialUpdateBodyFiltersOneEarlyExitDefault = false

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
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `gte` - gte\n\* `lt` - lt\n\* `lte` - lte'
                                            )
                                            .describe(
                                                'Operator used to compare the property value.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `gte` - gte\n\* `lt` - lt\n\* `lte` - lte'
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                            .describe('\* `is_set` - is_set\n\* `is_not_set` - is_not_set')
                                            .describe(
                                                'Existence operator.\n\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
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
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                            .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
                                            .describe(
                                                '\* `is_date_exact` - is_date_exact\n\* `is_date_before` - is_date_before\n\* `is_date_after` - is_date_after'
                                            )
                                            .describe(
                                                'Date comparison operator.\n\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before'
                                            ),
                                        value: zod
                                            .string()
                                            .describe('Date value in ISO format or relative date expression.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                                '\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_eq` - semver_eq\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_caret` - semver_caret\n\* `semver_wildcard` - semver_wildcard'
                                            )
                                            .describe(
                                                'Semantic version comparison operator.\n\n\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_eq` - semver_eq\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_caret` - semver_caret\n\* `semver_wildcard` - semver_wildcard'
                                            ),
                                        value: zod.string().describe('Semantic version string.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort', 'person', 'group'])
                                            .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')
                                            .optional()
                                            .describe(
                                                "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
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
                                                '\* `icontains_multi` - icontains_multi\n\* `not_icontains_multi` - not_icontains_multi'
                                            )
                                            .describe(
                                                'Multi-contains operator.\n\n\* `icontains_multi` - icontains_multi\n\* `not_icontains_multi` - not_icontains_multi'
                                            ),
                                        value: zod.array(zod.string()).describe('List of strings to evaluate against.'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['cohort'])
                                            .describe('\* `cohort` - cohort')
                                            .describe(
                                                'Cohort property type required for in\/not_in operators.\n\n\* `cohort` - cohort'
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
                                            .describe('\* `in` - in\n\* `not_in` - not_in')
                                            .describe(
                                                'Membership operator for cohort properties.\n\n\* `in` - in\n\* `not_in` - not_in'
                                            ),
                                        value: zod
                                            .unknown()
                                            .describe('Cohort comparison value (single or list, depending on usage).'),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('Property key used in this feature flag condition.'),
                                        type: zod
                                            .enum(['flag'])
                                            .describe('\* `flag` - flag')
                                            .describe(
                                                'Flag property type required for flag dependency checks.\n\n\* `flag` - flag'
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
                                            .describe('\* `flag_evaluates_to` - flag_evaluates_to')
                                            .describe(
                                                'Operator for feature flag dependency evaluation.\n\n\* `flag_evaluates_to` - flag_evaluates_to'
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
                .union([
                    zod.object({
                        variants: zod
                            .array(
                                zod.object({
                                    key: zod.string().describe('Unique key for this variant.'),
                                    name: zod.string().optional().describe('Human-readable name for this variant.'),
                                    rollout_percentage: zod.number().describe('Variant rollout percentage.'),
                                })
                            )
                            .describe('Variant definitions for multivariate feature flags.'),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe('Multivariate configuration for variant-based rollouts.'),
            aggregation_group_type_index: zod
                .number()
                .nullish()
                .describe('Group type index for group-based feature flags.'),
            payloads: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe('Optional payload values keyed by variant key.'),
            feature_enrollment: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment\/{flag_key}.'
                ),
            early_exit: zod
                .boolean()
                .default(featureFlagsPartialUpdateBodyFiltersOneEarlyExitDefault)
                .describe(
                    'When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups.'
                ),
        })
        .optional()
        .describe('Feature flag targeting configuration.'),
    active: zod.boolean().optional().describe('Whether the feature flag is active.'),
    archived: zod
        .boolean()
        .optional()
        .describe(
            'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
        ),
    tags: zod.array(zod.string()).optional().describe('Organizational tags for this feature flag.'),
    evaluation_contexts: zod
        .array(zod.string())
        .optional()
        .describe('Evaluation contexts that control where this flag evaluates at runtime.'),
    is_remote_configuration: zod
        .boolean()
        .nullish()
        .describe(
            'Whether this flag is a remote configuration flag that delivers a payload rather than gating a feature.'
        ),
    ensure_experience_continuity: zod
        .boolean()
        .nullish()
        .describe(
            "Whether to persist a user's flag value across the anonymous-to-identified transition (the 'persist across authentication steps' option). Incompatible with device_id bucketing."
        ),
    evaluation_runtime: zod
        .union([
            zod
                .enum(['server', 'client', 'all'])
                .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All'),
            zod.null(),
        ])
        .optional()
        .describe(
            "Where this flag is allowed to evaluate: 'server' (server-side SDKs only), 'client' (client-side SDKs only), or 'all' (both). Defaults to 'all'.\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All"
        ),
    bucketing_identifier: zod
        .union([
            zod
                .enum(['distinct_id', 'device_id'])
                .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'),
            zod.null(),
        ])
        .optional()
        .describe(
            "Identifier used to bucket users into rollout percentages and variants: 'distinct_id' (user ID, the default) or 'device_id'. Using 'device_id' is incompatible with ensure_experience_continuity=True.\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID"
        ),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
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
        archived: zod
            .boolean()
            .optional()
            .describe(
                'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        version: zod.number().default(featureFlagsCreateStaticCohortForFlagCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().optional(),
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
                '\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
            ),
        last_called_at: zod.iso
            .datetime({ offset: true })
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
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
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
        archived: zod
            .boolean()
            .optional()
            .describe(
                'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        version: zod.number().default(featureFlagsDashboardCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().optional(),
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
                '\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
            ),
        last_called_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsDashboardCreateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
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
        archived: zod
            .boolean()
            .optional()
            .describe(
                'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        version: zod.number().default(featureFlagsEnrichUsageDashboardCreateBodyVersionDefault),
        ensure_experience_continuity: zod.boolean().nullish(),
        rollback_conditions: zod.unknown().optional(),
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
                '\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours'
            )
            .optional()
            .describe(
                "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours"
            ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
            ),
        last_called_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod
            .boolean()
            .default(featureFlagsEnrichUsageDashboardCreateBodyShouldCreateUsageDashboardDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Test feature flag evaluation against a specific user at an optional point in time.
 *
 * This endpoint allows testing how a feature flag would evaluate for a specific user,
 * optionally at a historical timestamp. When a timestamp is provided, both the flag
 * conditions and person properties are evaluated as they existed at that time.
 */
export const FeatureFlagsTestEvaluationCreateBody = /* @__PURE__ */ zod.object({
    distinct_id: zod
        .string()
        .optional()
        .describe('User distinct ID to test against (mutually exclusive with person_id)'),
    person_id: zod.string().optional().describe('Person ID to test against (mutually exclusive with distinct_id)'),
    timestamp: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            'Optional point-in-time to evaluate the flag against — both flag conditions and person properties are reconstructed as they existed at that timestamp. ISO 8601 with timezone, e.g. ``2026-04-29T15:30:00Z`` or ``2026-04-29T15:30:00+00:00``. Naive timestamps (no timezone) are interpreted as UTC.'
        ),
    groups: zod
        .unknown()
        .optional()
        .describe('Groups for feature flag evaluation (JSON object, defaults to empty dict)'),
})

/**
 * Bulk delete feature flags by filter criteria or explicit IDs.
 *
 * Accepts either:
 * - {"filters": {...}} - Same filter params as list endpoint (search, active, type, etc.)
 * - {"ids": [...]} - Explicit list of flag IDs (no limit)
 *
 * Returns same format as bulk_delete for UI compatibility.
 *
 * Uses bulk operations for efficiency: database updates are batched and cache
 * invalidation happens once at the end rather than per-flag.
 */

export const FeatureFlagsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .object({
            active: zod
                .enum(['true', 'false', 'STALE'])
                .describe('\* `true` - true\n\* `false` - false\n\* `STALE` - STALE')
                .optional()
                .describe('Filter by active state.\n\n\* `true` - true\n\* `false` - false\n\* `STALE` - STALE'),
            created_by_id: zod.number().optional().describe('Filter to flags created by a specific user ID.'),
            search: zod.string().optional().describe('Search by feature flag key or name (case-insensitive).'),
            type: zod
                .enum(['boolean', 'multivariant', 'experiment', 'remote_config'])
                .describe(
                    '\* `boolean` - boolean\n\* `multivariant` - multivariant\n\* `experiment` - experiment\n\* `remote_config` - remote_config'
                )
                .optional()
                .describe(
                    'Filter by flag type.\n\n\* `boolean` - boolean\n\* `multivariant` - multivariant\n\* `experiment` - experiment\n\* `remote_config` - remote_config'
                ),
            evaluation_runtime: zod
                .enum(['server', 'client', 'all'])
                .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All')
                .optional()
                .describe(
                    'Filter by evaluation runtime.\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
                ),
            excluded_properties: zod
                .string()
                .optional()
                .describe('JSON-encoded property filter to exclude. Same shape as the list endpoint.'),
            tags: zod
                .array(zod.string())
                .optional()
                .describe('Tag names to filter by. Flags carrying at least one of these tags match.'),
            excluded_tags: zod
                .array(zod.string())
                .optional()
                .describe('Tag names to exclude. Flags carrying any of these tags are filtered out.'),
            has_evaluation_contexts: zod
                .boolean()
                .optional()
                .describe('When true, only matches flags with at least one evaluation context.'),
            archived: zod
                .boolean()
                .optional()
                .describe('Filter by archived state. When omitted, archived flags are excluded.'),
        })
        .describe("Allowed filter keys for bulk_delete — same shape as the list endpoint's query params.")
        .optional()
        .describe(
            "Filter criteria — same shape as the list endpoint's query params. Mutually exclusive with `ids`. Use this to bulk-delete by search\/active\/tags\/etc. instead of supplying explicit IDs."
        ),
    ids: zod
        .array(zod.number().min(1))
        .optional()
        .describe('Explicit feature flag IDs to soft-delete. Mutually exclusive with `filters`.'),
})

/**
 * Get feature flag keys by IDs.
 * Accepts a list of feature flag IDs and returns a mapping of ID to key.
 */
export const FeatureFlagsBulkKeysRetrieveBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.unknown())
        .optional()
        .describe(
            'Feature flag IDs to look up keys for. Strings of digits are also accepted; any other value is reported in the response `warning` field and otherwise ignored.'
        ),
})

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const featureFlagsBulkUpdateTagsCreateBodyIdsMax = 500

export const FeatureFlagsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(featureFlagsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsUserBlastRadiusCreateBody = /* @__PURE__ */ zod.object({
    condition: zod.record(zod.string(), zod.unknown()).describe('The release condition to evaluate'),
    group_type_index: zod
        .number()
        .nullish()
        .describe('Group type index for group-based flags (null for person-based flags)'),
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
        .describe('\* `FeatureFlag` - feature flag')
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n\* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true\/false to enable\/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesCreateBodyIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly'),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesCreateBodyCronExpressionMax).nullish(),
    end_date: zod.iso
        .datetime({ offset: true })
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
        .describe('\* `FeatureFlag` - feature flag')
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n\* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true\/false to enable\/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesUpdateBodyIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly'),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesUpdateBodyCronExpressionMax).nullish(),
    end_date: zod.iso
        .datetime({ offset: true })
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
        .describe('\* `FeatureFlag` - feature flag')
        .optional()
        .describe(
            'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n\* `FeatureFlag` - feature flag'
        ),
    payload: zod
        .unknown()
        .optional()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true\/false to enable\/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    is_recurring: zod
        .boolean()
        .default(scheduledChangesPartialUpdateBodyIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([
            zod
                .enum(['daily', 'weekly', 'monthly', 'yearly'])
                .describe('\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly'),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangesPartialUpdateBodyCronExpressionMax).nullish(),
    end_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
})
