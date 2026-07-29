/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 21 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const FeatureFlagsCopyFlagsCreateParams = /* @__PURE__ */ zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
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

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const FeatureFlagsListQueryParams = /* @__PURE__ */ zod.object({
    active: zod.enum(['STALE', 'false', 'true']).optional(),
    archived: zod
        .enum(['false', 'true'])
        .optional()
        .describe('Filter by archived state. When omitted, archived flags are excluded.'),
    created_by_id: zod
        .string()
        .optional()
        .describe(
            'Filter by the user(s) who created the feature flag. Accepts a single user ID, or a JSON-encoded \/ comma-separated list of user IDs to match any of them.'
        ),
    eligible_for_experiment: zod
        .enum(['true'])
        .optional()
        .describe(
            "When 'true', only return flags that can back an experiment: multivariate with 2-20 variants. Any other value is ignored."
        ),
    evaluation_runtime: zod
        .enum(['all', 'client', 'server'])
        .optional()
        .describe('Filter feature flags by their evaluation runtime.'),
    excluded_properties: zod
        .string()
        .optional()
        .describe('JSON-encoded list of feature flag keys to exclude from the results.'),
    excluded_tags: zod
        .string()
        .optional()
        .describe('JSON-encoded list of tag names to exclude. Flags carrying any of these tags are filtered out.'),
    has_evaluation_contexts: zod
        .enum(['false', 'true'])
        .optional()
        .describe(
            "Filter feature flags by presence of evaluation contexts. 'true' returns only flags with at least one evaluation context, 'false' returns only flags without."
        ),
    key: zod.string().optional().describe('Filter by exact feature flag key match. Case insensitive.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Search by feature flag key or name. Case insensitive.'),
    tags: zod.string().optional().describe('JSON-encoded list of tag names to filter feature flags by.'),
    type: zod.enum(['boolean', 'experiment', 'multivariant', 'remote_config']).optional(),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const featureFlagsCreateBodyFiltersOneGroupsItemPropertiesItemGroupTypeIndexMin = -2147483648
export const featureFlagsCreateBodyFiltersOneGroupsItemPropertiesItemGroupTypeIndexMax = 2147483647

export const featureFlagsCreateBodyFiltersOneGroupsItemRolloutPercentageMin = 0
export const featureFlagsCreateBodyFiltersOneGroupsItemRolloutPercentageMax = 100

export const featureFlagsCreateBodyFiltersOneGroupsItemAggregationGroupTypeIndexMin = -2147483648
export const featureFlagsCreateBodyFiltersOneGroupsItemAggregationGroupTypeIndexMax = 2147483647

export const featureFlagsCreateBodyFiltersOneGroupsItemExposureFrozenCohortMin = -2147483648
export const featureFlagsCreateBodyFiltersOneGroupsItemExposureFrozenCohortMax = 2147483647

export const featureFlagsCreateBodyFiltersOneMultivariateOneVariantsItemKeyMax = 400

export const featureFlagsCreateBodyFiltersOneMultivariateOneVariantsItemKeyRegExp = new RegExp('^[a-zA-Z0-9_.\/-]+$')
export const featureFlagsCreateBodyFiltersOneMultivariateOneVariantsItemRolloutPercentageMin = 0
export const featureFlagsCreateBodyFiltersOneMultivariateOneVariantsItemRolloutPercentageMax = 100

export const featureFlagsCreateBodyFiltersOneAggregationGroupTypeIndexMin = -2147483648
export const featureFlagsCreateBodyFiltersOneAggregationGroupTypeIndexMax = 2147483647

export const featureFlagsCreateBodyFiltersOneHoldoutOneIdMin = -2147483648
export const featureFlagsCreateBodyFiltersOneHoldoutOneIdMax = 2147483647

export const featureFlagsCreateBodyFiltersOneHoldoutOneExclusionPercentageMin = 0
export const featureFlagsCreateBodyFiltersOneHoldoutOneExclusionPercentageMax = 100

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
                    zod
                        .object({
                            properties: zod
                                .array(
                                    zod
                                        .object({
                                            key: zod
                                                .string()
                                                .describe(
                                                    'Property key used in this feature flag condition. Numbers are normalized to strings.'
                                                ),
                                            value: zod
                                                .unknown()
                                                .optional()
                                                .describe(
                                                    'Comparison value for the property filter. Valid shapes depend on the operator.'
                                                ),
                                            type: zod
                                                .enum(['person', 'cohort', 'group', 'flag'])
                                                .describe(
                                                    '\* `person` - person\n\* `cohort` - cohort\n\* `group` - group\n\* `flag` - flag'
                                                )
                                                .describe(
                                                    "Property filter type. One of 'person', 'cohort', 'group', or 'flag'.\n\n\* `person` - person\n\* `cohort` - cohort\n\* `group` - group\n\* `flag` - flag"
                                                ),
                                            operator: zod
                                                .union([
                                                    zod
                                                        .enum([
                                                            'exact',
                                                            'flag_evaluates_to',
                                                            'gt',
                                                            'gte',
                                                            'icontains',
                                                            'icontains_multi',
                                                            'in',
                                                            'is_date_after',
                                                            'is_date_before',
                                                            'is_date_exact',
                                                            'is_not',
                                                            'is_not_set',
                                                            'is_set',
                                                            'lt',
                                                            'lte',
                                                            'not_icontains',
                                                            'not_icontains_multi',
                                                            'not_in',
                                                            'not_regex',
                                                            'regex',
                                                            'semver_caret',
                                                            'semver_eq',
                                                            'semver_gt',
                                                            'semver_gte',
                                                            'semver_lt',
                                                            'semver_lte',
                                                            'semver_neq',
                                                            'semver_tilde',
                                                            'semver_wildcard',
                                                        ])
                                                        .describe(
                                                            '\* `exact` - exact\n\* `flag_evaluates_to` - flag_evaluates_to\n\* `gt` - gt\n\* `gte` - gte\n\* `icontains` - icontains\n\* `icontains_multi` - icontains_multi\n\* `in` - in\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `is_date_exact` - is_date_exact\n\* `is_not` - is_not\n\* `is_not_set` - is_not_set\n\* `is_set` - is_set\n\* `lt` - lt\n\* `lte` - lte\n\* `not_icontains` - not_icontains\n\* `not_icontains_multi` - not_icontains_multi\n\* `not_in` - not_in\n\* `not_regex` - not_regex\n\* `regex` - regex\n\* `semver_caret` - semver_caret\n\* `semver_eq` - semver_eq\n\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_wildcard` - semver_wildcard'
                                                        ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    'Operator used to compare the property value. Null means exact match.\n\n\* `exact` - exact\n\* `flag_evaluates_to` - flag_evaluates_to\n\* `gt` - gt\n\* `gte` - gte\n\* `icontains` - icontains\n\* `icontains_multi` - icontains_multi\n\* `in` - in\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `is_date_exact` - is_date_exact\n\* `is_not` - is_not\n\* `is_not_set` - is_not_set\n\* `is_set` - is_set\n\* `lt` - lt\n\* `lte` - lte\n\* `not_icontains` - not_icontains\n\* `not_icontains_multi` - not_icontains_multi\n\* `not_in` - not_in\n\* `not_regex` - not_regex\n\* `regex` - regex\n\* `semver_caret` - semver_caret\n\* `semver_eq` - semver_eq\n\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_wildcard` - semver_wildcard'
                                                ),
                                            group_type_index: zod
                                                .number()
                                                .min(
                                                    featureFlagsCreateBodyFiltersOneGroupsItemPropertiesItemGroupTypeIndexMin
                                                )
                                                .max(
                                                    featureFlagsCreateBodyFiltersOneGroupsItemPropertiesItemGroupTypeIndexMax
                                                )
                                                .nullish()
                                                .describe('Group type index when using group-based filters.'),
                                            negation: zod
                                                .boolean()
                                                .nullish()
                                                .describe('Whether the property condition is negated.'),
                                            label: zod
                                                .string()
                                                .nullish()
                                                .describe(
                                                    'Display-only label for this property filter, shown in the UI.'
                                                ),
                                            cohort_name: zod
                                                .string()
                                                .nullish()
                                                .describe(
                                                    'Display name of the referenced cohort. Injected on read and echoed back by clients.'
                                                ),
                                            group_key_names: zod
                                                .unknown()
                                                .optional()
                                                .describe(
                                                    'Display names for group keys, keyed by group key. Injected on read and echoed back by clients.'
                                                ),
                                        })
                                        .describe(
                                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                                        )
                                )
                                .nullish()
                                .describe('Property conditions for this release condition group.'),
                            rollout_percentage: zod
                                .number()
                                .min(featureFlagsCreateBodyFiltersOneGroupsItemRolloutPercentageMin)
                                .max(featureFlagsCreateBodyFiltersOneGroupsItemRolloutPercentageMax)
                                .nullish()
                                .describe('Rollout percentage for this release condition group, between 0 and 100.'),
                            variant: zod.string().nullish().describe('Variant key override for multivariate flags.'),
                            aggregation_group_type_index: zod
                                .number()
                                .min(featureFlagsCreateBodyFiltersOneGroupsItemAggregationGroupTypeIndexMin)
                                .max(featureFlagsCreateBodyFiltersOneGroupsItemAggregationGroupTypeIndexMax)
                                .nullish()
                                .describe(
                                    'Group type index for this condition set. Null means person-level aggregation; absent falls back to the flag-level value.'
                                ),
                            description: zod
                                .string()
                                .nullish()
                                .describe('Display-only description for this condition group, shown in the UI.'),
                            sort_key: zod
                                .unknown()
                                .optional()
                                .describe(
                                    'Opaque UI ordering key for this condition group (string or number). Preserved as-is.'
                                ),
                            exposure_frozen: zod
                                .boolean()
                                .nullish()
                                .describe(
                                    'Set when an experiment froze exposure by narrowing this group to a snapshot cohort.'
                                ),
                            exposure_frozen_cohort: zod
                                .number()
                                .min(featureFlagsCreateBodyFiltersOneGroupsItemExposureFrozenCohortMin)
                                .max(featureFlagsCreateBodyFiltersOneGroupsItemExposureFrozenCohortMax)
                                .nullish()
                                .describe(
                                    'ID of the snapshot cohort this group was narrowed to when experiment exposure was frozen.'
                                ),
                        })
                        .describe(
                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                        )
                )
                .optional()
                .describe('Release condition groups for the feature flag.'),
            multivariate: zod
                .union([
                    zod
                        .object({
                            variants: zod
                                .array(
                                    zod
                                        .object({
                                            key: zod
                                                .string()
                                                .max(featureFlagsCreateBodyFiltersOneMultivariateOneVariantsItemKeyMax)
                                                .regex(
                                                    featureFlagsCreateBodyFiltersOneMultivariateOneVariantsItemKeyRegExp
                                                )
                                                .describe(
                                                    'Unique key for this variant. Letters, numbers, hyphens, underscores, dots, and slashes; at most 400 characters.'
                                                ),
                                            name: zod
                                                .string()
                                                .nullish()
                                                .describe('Human-readable name for this variant.'),
                                            rollout_percentage: zod
                                                .number()
                                                .min(
                                                    featureFlagsCreateBodyFiltersOneMultivariateOneVariantsItemRolloutPercentageMin
                                                )
                                                .max(
                                                    featureFlagsCreateBodyFiltersOneMultivariateOneVariantsItemRolloutPercentageMax
                                                )
                                                .describe('Variant rollout percentage, between 0 and 100.'),
                                            description: zod
                                                .string()
                                                .nullish()
                                                .describe(
                                                    'Display-only description for this variant, shown in the UI.'
                                                ),
                                        })
                                        .describe(
                                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                                        )
                                )
                                .describe('Variant definitions for multivariate feature flags.'),
                        })
                        .describe(
                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe('Multivariate configuration for variant-based rollouts.'),
            aggregation_group_type_index: zod
                .number()
                .min(featureFlagsCreateBodyFiltersOneAggregationGroupTypeIndexMin)
                .max(featureFlagsCreateBodyFiltersOneAggregationGroupTypeIndexMax)
                .nullish()
                .describe('Group type index for group-based feature flags. Null means person-level aggregation.'),
            payloads: zod
                .record(zod.string(), zod.unknown())
                .nullish()
                .describe(
                    "Payloads keyed by variant key (multivariate flags) or 'true' (boolean flags). Values are stored as JSON-encoded strings; non-string JSON values are normalized on write."
                ),
            feature_enrollment: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment\/{flag_key}.'
                ),
            holdout: zod
                .union([
                    zod
                        .object({
                            id: zod
                                .number()
                                .min(featureFlagsCreateBodyFiltersOneHoldoutOneIdMin)
                                .max(featureFlagsCreateBodyFiltersOneHoldoutOneIdMax)
                                .describe('ID of the experiment holdout this flag belongs to.'),
                            exclusion_percentage: zod
                                .number()
                                .min(featureFlagsCreateBodyFiltersOneHoldoutOneExclusionPercentageMin)
                                .max(featureFlagsCreateBodyFiltersOneHoldoutOneExclusionPercentageMax)
                                .describe('Percentage of users held out from the flag, between 0 and 100.'),
                        })
                        .describe(
                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe('Experiment holdout configuration for this flag.'),
            early_exit: zod
                .boolean()
                .nullish()
                .describe(
                    'When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups.'
                ),
        })
        .describe(
            'Feature flag targeting configuration: release condition groups, multivariate variants, and payloads.'
        )
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
export const FeatureFlagsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const featureFlagsPartialUpdateBodyFiltersOneGroupsItemPropertiesItemGroupTypeIndexMin = -2147483648
export const featureFlagsPartialUpdateBodyFiltersOneGroupsItemPropertiesItemGroupTypeIndexMax = 2147483647

export const featureFlagsPartialUpdateBodyFiltersOneGroupsItemRolloutPercentageMin = 0
export const featureFlagsPartialUpdateBodyFiltersOneGroupsItemRolloutPercentageMax = 100

export const featureFlagsPartialUpdateBodyFiltersOneGroupsItemAggregationGroupTypeIndexMin = -2147483648
export const featureFlagsPartialUpdateBodyFiltersOneGroupsItemAggregationGroupTypeIndexMax = 2147483647

export const featureFlagsPartialUpdateBodyFiltersOneGroupsItemExposureFrozenCohortMin = -2147483648
export const featureFlagsPartialUpdateBodyFiltersOneGroupsItemExposureFrozenCohortMax = 2147483647

export const featureFlagsPartialUpdateBodyFiltersOneMultivariateOneVariantsItemKeyMax = 400

export const featureFlagsPartialUpdateBodyFiltersOneMultivariateOneVariantsItemKeyRegExp = new RegExp(
    '^[a-zA-Z0-9_.\/-]+$'
)
export const featureFlagsPartialUpdateBodyFiltersOneMultivariateOneVariantsItemRolloutPercentageMin = 0
export const featureFlagsPartialUpdateBodyFiltersOneMultivariateOneVariantsItemRolloutPercentageMax = 100

export const featureFlagsPartialUpdateBodyFiltersOneAggregationGroupTypeIndexMin = -2147483648
export const featureFlagsPartialUpdateBodyFiltersOneAggregationGroupTypeIndexMax = 2147483647

export const featureFlagsPartialUpdateBodyFiltersOneHoldoutOneIdMin = -2147483648
export const featureFlagsPartialUpdateBodyFiltersOneHoldoutOneIdMax = 2147483647

export const featureFlagsPartialUpdateBodyFiltersOneHoldoutOneExclusionPercentageMin = 0
export const featureFlagsPartialUpdateBodyFiltersOneHoldoutOneExclusionPercentageMax = 100

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
                    zod
                        .object({
                            properties: zod
                                .array(
                                    zod
                                        .object({
                                            key: zod
                                                .string()
                                                .describe(
                                                    'Property key used in this feature flag condition. Numbers are normalized to strings.'
                                                ),
                                            value: zod
                                                .unknown()
                                                .optional()
                                                .describe(
                                                    'Comparison value for the property filter. Valid shapes depend on the operator.'
                                                ),
                                            type: zod
                                                .enum(['person', 'cohort', 'group', 'flag'])
                                                .describe(
                                                    '\* `person` - person\n\* `cohort` - cohort\n\* `group` - group\n\* `flag` - flag'
                                                )
                                                .describe(
                                                    "Property filter type. One of 'person', 'cohort', 'group', or 'flag'.\n\n\* `person` - person\n\* `cohort` - cohort\n\* `group` - group\n\* `flag` - flag"
                                                ),
                                            operator: zod
                                                .union([
                                                    zod
                                                        .enum([
                                                            'exact',
                                                            'flag_evaluates_to',
                                                            'gt',
                                                            'gte',
                                                            'icontains',
                                                            'icontains_multi',
                                                            'in',
                                                            'is_date_after',
                                                            'is_date_before',
                                                            'is_date_exact',
                                                            'is_not',
                                                            'is_not_set',
                                                            'is_set',
                                                            'lt',
                                                            'lte',
                                                            'not_icontains',
                                                            'not_icontains_multi',
                                                            'not_in',
                                                            'not_regex',
                                                            'regex',
                                                            'semver_caret',
                                                            'semver_eq',
                                                            'semver_gt',
                                                            'semver_gte',
                                                            'semver_lt',
                                                            'semver_lte',
                                                            'semver_neq',
                                                            'semver_tilde',
                                                            'semver_wildcard',
                                                        ])
                                                        .describe(
                                                            '\* `exact` - exact\n\* `flag_evaluates_to` - flag_evaluates_to\n\* `gt` - gt\n\* `gte` - gte\n\* `icontains` - icontains\n\* `icontains_multi` - icontains_multi\n\* `in` - in\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `is_date_exact` - is_date_exact\n\* `is_not` - is_not\n\* `is_not_set` - is_not_set\n\* `is_set` - is_set\n\* `lt` - lt\n\* `lte` - lte\n\* `not_icontains` - not_icontains\n\* `not_icontains_multi` - not_icontains_multi\n\* `not_in` - not_in\n\* `not_regex` - not_regex\n\* `regex` - regex\n\* `semver_caret` - semver_caret\n\* `semver_eq` - semver_eq\n\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_wildcard` - semver_wildcard'
                                                        ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    'Operator used to compare the property value. Null means exact match.\n\n\* `exact` - exact\n\* `flag_evaluates_to` - flag_evaluates_to\n\* `gt` - gt\n\* `gte` - gte\n\* `icontains` - icontains\n\* `icontains_multi` - icontains_multi\n\* `in` - in\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `is_date_exact` - is_date_exact\n\* `is_not` - is_not\n\* `is_not_set` - is_not_set\n\* `is_set` - is_set\n\* `lt` - lt\n\* `lte` - lte\n\* `not_icontains` - not_icontains\n\* `not_icontains_multi` - not_icontains_multi\n\* `not_in` - not_in\n\* `not_regex` - not_regex\n\* `regex` - regex\n\* `semver_caret` - semver_caret\n\* `semver_eq` - semver_eq\n\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_wildcard` - semver_wildcard'
                                                ),
                                            group_type_index: zod
                                                .number()
                                                .min(
                                                    featureFlagsPartialUpdateBodyFiltersOneGroupsItemPropertiesItemGroupTypeIndexMin
                                                )
                                                .max(
                                                    featureFlagsPartialUpdateBodyFiltersOneGroupsItemPropertiesItemGroupTypeIndexMax
                                                )
                                                .nullish()
                                                .describe('Group type index when using group-based filters.'),
                                            negation: zod
                                                .boolean()
                                                .nullish()
                                                .describe('Whether the property condition is negated.'),
                                            label: zod
                                                .string()
                                                .nullish()
                                                .describe(
                                                    'Display-only label for this property filter, shown in the UI.'
                                                ),
                                            cohort_name: zod
                                                .string()
                                                .nullish()
                                                .describe(
                                                    'Display name of the referenced cohort. Injected on read and echoed back by clients.'
                                                ),
                                            group_key_names: zod
                                                .unknown()
                                                .optional()
                                                .describe(
                                                    'Display names for group keys, keyed by group key. Injected on read and echoed back by clients.'
                                                ),
                                        })
                                        .describe(
                                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                                        )
                                )
                                .nullish()
                                .describe('Property conditions for this release condition group.'),
                            rollout_percentage: zod
                                .number()
                                .min(featureFlagsPartialUpdateBodyFiltersOneGroupsItemRolloutPercentageMin)
                                .max(featureFlagsPartialUpdateBodyFiltersOneGroupsItemRolloutPercentageMax)
                                .nullish()
                                .describe('Rollout percentage for this release condition group, between 0 and 100.'),
                            variant: zod.string().nullish().describe('Variant key override for multivariate flags.'),
                            aggregation_group_type_index: zod
                                .number()
                                .min(featureFlagsPartialUpdateBodyFiltersOneGroupsItemAggregationGroupTypeIndexMin)
                                .max(featureFlagsPartialUpdateBodyFiltersOneGroupsItemAggregationGroupTypeIndexMax)
                                .nullish()
                                .describe(
                                    'Group type index for this condition set. Null means person-level aggregation; absent falls back to the flag-level value.'
                                ),
                            description: zod
                                .string()
                                .nullish()
                                .describe('Display-only description for this condition group, shown in the UI.'),
                            sort_key: zod
                                .unknown()
                                .optional()
                                .describe(
                                    'Opaque UI ordering key for this condition group (string or number). Preserved as-is.'
                                ),
                            exposure_frozen: zod
                                .boolean()
                                .nullish()
                                .describe(
                                    'Set when an experiment froze exposure by narrowing this group to a snapshot cohort.'
                                ),
                            exposure_frozen_cohort: zod
                                .number()
                                .min(featureFlagsPartialUpdateBodyFiltersOneGroupsItemExposureFrozenCohortMin)
                                .max(featureFlagsPartialUpdateBodyFiltersOneGroupsItemExposureFrozenCohortMax)
                                .nullish()
                                .describe(
                                    'ID of the snapshot cohort this group was narrowed to when experiment exposure was frozen.'
                                ),
                        })
                        .describe(
                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                        )
                )
                .optional()
                .describe('Release condition groups for the feature flag.'),
            multivariate: zod
                .union([
                    zod
                        .object({
                            variants: zod
                                .array(
                                    zod
                                        .object({
                                            key: zod
                                                .string()
                                                .max(
                                                    featureFlagsPartialUpdateBodyFiltersOneMultivariateOneVariantsItemKeyMax
                                                )
                                                .regex(
                                                    featureFlagsPartialUpdateBodyFiltersOneMultivariateOneVariantsItemKeyRegExp
                                                )
                                                .describe(
                                                    'Unique key for this variant. Letters, numbers, hyphens, underscores, dots, and slashes; at most 400 characters.'
                                                ),
                                            name: zod
                                                .string()
                                                .nullish()
                                                .describe('Human-readable name for this variant.'),
                                            rollout_percentage: zod
                                                .number()
                                                .min(
                                                    featureFlagsPartialUpdateBodyFiltersOneMultivariateOneVariantsItemRolloutPercentageMin
                                                )
                                                .max(
                                                    featureFlagsPartialUpdateBodyFiltersOneMultivariateOneVariantsItemRolloutPercentageMax
                                                )
                                                .describe('Variant rollout percentage, between 0 and 100.'),
                                            description: zod
                                                .string()
                                                .nullish()
                                                .describe(
                                                    'Display-only description for this variant, shown in the UI.'
                                                ),
                                        })
                                        .describe(
                                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                                        )
                                )
                                .describe('Variant definitions for multivariate feature flags.'),
                        })
                        .describe(
                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe('Multivariate configuration for variant-based rollouts.'),
            aggregation_group_type_index: zod
                .number()
                .min(featureFlagsPartialUpdateBodyFiltersOneAggregationGroupTypeIndexMin)
                .max(featureFlagsPartialUpdateBodyFiltersOneAggregationGroupTypeIndexMax)
                .nullish()
                .describe('Group type index for group-based feature flags. Null means person-level aggregation.'),
            payloads: zod
                .record(zod.string(), zod.unknown())
                .nullish()
                .describe(
                    "Payloads keyed by variant key (multivariate flags) or 'true' (boolean flags). Values are stored as JSON-encoded strings; non-string JSON values are normalized on write."
                ),
            feature_enrollment: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment\/{flag_key}.'
                ),
            holdout: zod
                .union([
                    zod
                        .object({
                            id: zod
                                .number()
                                .min(featureFlagsPartialUpdateBodyFiltersOneHoldoutOneIdMin)
                                .max(featureFlagsPartialUpdateBodyFiltersOneHoldoutOneIdMax)
                                .describe('ID of the experiment holdout this flag belongs to.'),
                            exclusion_percentage: zod
                                .number()
                                .min(featureFlagsPartialUpdateBodyFiltersOneHoldoutOneExclusionPercentageMin)
                                .max(featureFlagsPartialUpdateBodyFiltersOneHoldoutOneExclusionPercentageMax)
                                .describe('Percentage of users held out from the flag, between 0 and 100.'),
                        })
                        .describe(
                            'DRF drops keys without a declared field silently; this makes the drop observable.\n\nDuring an audit run an `unknown_keys_sink` in the serializer context collects them;\notherwise non-legacy unknown keys are logged so we learn whether junk keys happen in\nthe wild before enforcement flips on.'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe('Experiment holdout configuration for this flag.'),
            early_exit: zod
                .boolean()
                .nullish()
                .describe(
                    'When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups.'
                ),
        })
        .describe(
            'Feature flag targeting configuration: release condition groups, multivariate variants, and payloads.'
        )
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
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const FeatureFlagsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsActivityRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const featureFlagsActivityRetrieveQueryLimitDefault = 10

export const featureFlagsActivityRetrieveQueryPageDefault = 1

export const FeatureFlagsActivityRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .min(1)
        .default(featureFlagsActivityRetrieveQueryLimitDefault)
        .describe('Number of items per page'),
    page: zod.number().min(1).default(featureFlagsActivityRetrieveQueryPageDefault).describe('Page number'),
})

/**
 * Get other active flags that depend on this flag.
 */
export const FeatureFlagsDependentFlagsListParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsStatusRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Test feature flag evaluation against a specific user at an optional point in time.
 *
 * This endpoint allows testing how a feature flag would evaluate for a specific user,
 * optionally at a historical timestamp. When a timestamp is provided, both the flag
 * conditions and person properties are evaluated as they existed at that time.
 */
export const FeatureFlagsTestEvaluationCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this feature flag.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
export const FeatureFlagsBulkDeleteCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
export const FeatureFlagsBulkKeysRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
export const FeatureFlagsBulkUpdateTagsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
export const FeatureFlagsEvaluationReasonsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const featureFlagsEvaluationReasonsRetrieveQueryGroupsDefault = `{}`

export const FeatureFlagsEvaluationReasonsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    distinct_id: zod.string().min(1).describe('User distinct ID'),
    flag_keys: zod
        .array(zod.string())
        .optional()
        .describe(
            'Optional list of flag keys to scope the response to. When omitted, evaluation reasons are returned for every flag in the project, which can be a very large payload on projects with many flags. Pass the specific flag(s) you are debugging to keep the response small. Accepts either repeated query params (flag_keys=a&flag_keys=b) or a JSON array string (flag_keys=[\"a\",\"b\"]).'
        ),
    groups: zod
        .string()
        .default(featureFlagsEvaluationReasonsRetrieveQueryGroupsDefault)
        .describe('Groups for feature flag evaluation (JSON object string)'),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsMyFlagsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const featureFlagsMyFlagsRetrieveQueryGroupsDefault = `{}`

export const FeatureFlagsMyFlagsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    groups: zod
        .string()
        .default(featureFlagsMyFlagsRetrieveQueryGroupsDefault)
        .describe('Groups for feature flag evaluation (JSON object string)'),
})

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsUserBlastRadiusCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
export const ScheduledChangesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ScheduledChangesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    model_name: zod
        .string()
        .optional()
        .describe('Filter by model type. Use \"FeatureFlag\" to see feature flag schedules.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    record_id: zod.string().optional().describe('Filter by the ID of a specific feature flag.'),
})

/**
 * Create, read, update and delete scheduled changes.
 */
export const ScheduledChangesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
export const ScheduledChangesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this scheduled change.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, read, update and delete scheduled changes.
 */
export const ScheduledChangesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this scheduled change.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const scheduledChangesPartialUpdateBodyRecordIdMax = 200

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
        .optional()
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

/**
 * Create, read, update and delete scheduled changes.
 */
export const ScheduledChangesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this scheduled change.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
