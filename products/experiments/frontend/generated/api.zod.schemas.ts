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

export const PropertyGroupTypeEnumApi = zod
    .enum(['cohort', 'person', 'group'])
    .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')

export type PropertyGroupTypeEnumApi = zod.input<typeof PropertyGroupTypeEnumApi>
export type PropertyGroupTypeEnumApiOutput = zod.output<typeof PropertyGroupTypeEnumApi>

export const FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi = zod
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
        'gte',
        'lt',
        'lte',
    ])
    .describe(
        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `gte` - gte\n\* `lt` - lt\n\* `lte` - lte'
    )

export type FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertyGenericSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertyGenericSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    value: zod
        .unknown()
        .describe('Comparison value for the property filter. Supports strings, numbers, booleans, and arrays.'),
    operator: FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi.describe(
        'Operator used to compare the property value.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `gte` - gte\n\* `lt` - lt\n\* `lte` - lte'
    ),
})

export type FeatureFlagFilterPropertyGenericSchemaApi = zod.input<typeof FeatureFlagFilterPropertyGenericSchemaApi>
export type FeatureFlagFilterPropertyGenericSchemaApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyGenericSchemaApi
>

export const ExistenceOperatorEnumApi = zod
    .enum(['is_set', 'is_not_set'])
    .describe('\* `is_set` - is_set\n\* `is_not_set` - is_not_set')

export type ExistenceOperatorEnumApi = zod.input<typeof ExistenceOperatorEnumApi>
export type ExistenceOperatorEnumApiOutput = zod.output<typeof ExistenceOperatorEnumApi>

export const FeatureFlagFilterPropertyExistsSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: ExistenceOperatorEnumApi.describe(
        'Existence operator.\n\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
    ),
    value: zod.unknown().optional().describe('Optional value. Runtime behavior determines whether this is ignored.'),
})

export type FeatureFlagFilterPropertyExistsSchemaApi = zod.input<typeof FeatureFlagFilterPropertyExistsSchemaApi>
export type FeatureFlagFilterPropertyExistsSchemaApiOutput = zod.output<typeof FeatureFlagFilterPropertyExistsSchemaApi>

export const DateOperatorEnumApi = zod
    .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
    .describe(
        '\* `is_date_exact` - is_date_exact\n\* `is_date_before` - is_date_before\n\* `is_date_after` - is_date_after'
    )

export type DateOperatorEnumApi = zod.input<typeof DateOperatorEnumApi>
export type DateOperatorEnumApiOutput = zod.output<typeof DateOperatorEnumApi>

export const FeatureFlagFilterPropertyDateSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: DateOperatorEnumApi.describe(
        'Date comparison operator.\n\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before'
    ),
    value: zod.string().describe('Date value in ISO format or relative date expression.'),
})

export type FeatureFlagFilterPropertyDateSchemaApi = zod.input<typeof FeatureFlagFilterPropertyDateSchemaApi>
export type FeatureFlagFilterPropertyDateSchemaApiOutput = zod.output<typeof FeatureFlagFilterPropertyDateSchemaApi>

export const FeatureFlagFilterPropertySemverSchemaOperatorEnumApi = zod
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

export type FeatureFlagFilterPropertySemverSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertySemverSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertySemverSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertySemverSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertySemverSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: FeatureFlagFilterPropertySemverSchemaOperatorEnumApi.describe(
        'Semantic version comparison operator.\n\n\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_eq` - semver_eq\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_caret` - semver_caret\n\* `semver_wildcard` - semver_wildcard'
    ),
    value: zod.string().describe('Semantic version string.'),
})

export type FeatureFlagFilterPropertySemverSchemaApi = zod.input<typeof FeatureFlagFilterPropertySemverSchemaApi>
export type FeatureFlagFilterPropertySemverSchemaApiOutput = zod.output<typeof FeatureFlagFilterPropertySemverSchemaApi>

export const FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi = zod
    .enum(['icontains_multi', 'not_icontains_multi'])
    .describe('\* `icontains_multi` - icontains_multi\n\* `not_icontains_multi` - not_icontains_multi')

export type FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertyMultiContainsSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi.describe(
        'Multi-contains operator.\n\n\* `icontains_multi` - icontains_multi\n\* `not_icontains_multi` - not_icontains_multi'
    ),
    value: zod.array(zod.string()).describe('List of strings to evaluate against.'),
})

export type FeatureFlagFilterPropertyMultiContainsSchemaApi = zod.input<
    typeof FeatureFlagFilterPropertyMultiContainsSchemaApi
>
export type FeatureFlagFilterPropertyMultiContainsSchemaApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyMultiContainsSchemaApi
>

export const FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi = zod.enum(['cohort']).describe('\* `cohort` - cohort')

export type FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi
>
export type FeatureFlagFilterPropertyCohortInSchemaTypeEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi
>

export const FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi = zod
    .enum(['in', 'not_in'])
    .describe('\* `in` - in\n\* `not_in` - not_in')

export type FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertyCohortInSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi.describe(
        'Cohort property type required for in\/not_in operators.\n\n\* `cohort` - cohort'
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi.describe(
        'Membership operator for cohort properties.\n\n\* `in` - in\n\* `not_in` - not_in'
    ),
    value: zod.unknown().describe('Cohort comparison value (single or list, depending on usage).'),
})

export type FeatureFlagFilterPropertyCohortInSchemaApi = zod.input<typeof FeatureFlagFilterPropertyCohortInSchemaApi>
export type FeatureFlagFilterPropertyCohortInSchemaApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyCohortInSchemaApi
>

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi = zod.enum(['flag']).describe('\* `flag` - flag')

export type FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi
>
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi
>

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi = zod
    .enum(['flag_evaluates_to'])
    .describe('\* `flag_evaluates_to` - flag_evaluates_to')

export type FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi.describe(
        'Flag property type required for flag dependency checks.\n\n\* `flag` - flag'
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi.describe(
        'Operator for feature flag dependency evaluation.\n\n\* `flag_evaluates_to` - flag_evaluates_to'
    ),
    value: zod.unknown().describe('Value to compare flag evaluation against.'),
})

export type FeatureFlagFilterPropertyFlagEvaluatesSchemaApi = zod.input<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaApi
>
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaApi
>

export const FeatureFlagFilterPropertySchemaApi = zod.union([
    FeatureFlagFilterPropertyGenericSchemaApi,
    FeatureFlagFilterPropertyExistsSchemaApi,
    FeatureFlagFilterPropertyDateSchemaApi,
    FeatureFlagFilterPropertySemverSchemaApi,
    FeatureFlagFilterPropertyMultiContainsSchemaApi,
    FeatureFlagFilterPropertyCohortInSchemaApi,
    FeatureFlagFilterPropertyFlagEvaluatesSchemaApi,
])

export type FeatureFlagFilterPropertySchemaApi = zod.input<typeof FeatureFlagFilterPropertySchemaApi>
export type FeatureFlagFilterPropertySchemaApiOutput = zod.output<typeof FeatureFlagFilterPropertySchemaApi>

export const FeatureFlagConditionGroupSchemaApi = zod.object({
    properties: zod
        .array(FeatureFlagFilterPropertySchemaApi)
        .optional()
        .describe('Property conditions for this release condition group.'),
    rollout_percentage: zod.number().optional().describe('Rollout percentage for this release condition group.'),
    variant: zod.string().nullish().describe('Variant key override for multivariate flags.'),
    aggregation_group_type_index: zod
        .number()
        .nullish()
        .describe('Group type index for this condition set. None means person-level aggregation.'),
})

export type FeatureFlagConditionGroupSchemaApi = zod.input<typeof FeatureFlagConditionGroupSchemaApi>
export type FeatureFlagConditionGroupSchemaApiOutput = zod.output<typeof FeatureFlagConditionGroupSchemaApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const experimentHoldoutApiNameMax = 400

export const experimentHoldoutApiDescriptionMax = 400

export const ExperimentHoldoutApi = zod
    .object({
        id: zod.number(),
        name: zod.string().max(experimentHoldoutApiNameMax).describe('Human-readable name for the holdout group.'),
        description: zod
            .string()
            .max(experimentHoldoutApiDescriptionMax)
            .nullish()
            .describe('Optional description of what this holdout reserves and why.'),
        filters: zod
            .array(FeatureFlagConditionGroupSchemaApi)
            .optional()
            .describe(
                "Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the \*\*exclusion\*\* percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person\/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout."
            ),
        created_by: UserBasicApi,
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('A holdout group — a stable slice of users excluded from experiment exposure.')

export type ExperimentHoldoutApi = zod.input<typeof ExperimentHoldoutApi>
export type ExperimentHoldoutApiOutput = zod.output<typeof ExperimentHoldoutApi>

export const PaginatedExperimentHoldoutListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ExperimentHoldoutApi),
})

export type PaginatedExperimentHoldoutListApi = zod.input<typeof PaginatedExperimentHoldoutListApi>
export type PaginatedExperimentHoldoutListApiOutput = zod.output<typeof PaginatedExperimentHoldoutListApi>

export const patchedExperimentHoldoutApiNameMax = 400

export const patchedExperimentHoldoutApiDescriptionMax = 400

export const PatchedExperimentHoldoutApi = zod
    .object({
        id: zod.number().optional(),
        name: zod
            .string()
            .max(patchedExperimentHoldoutApiNameMax)
            .optional()
            .describe('Human-readable name for the holdout group.'),
        description: zod
            .string()
            .max(patchedExperimentHoldoutApiDescriptionMax)
            .nullish()
            .describe('Optional description of what this holdout reserves and why.'),
        filters: zod
            .array(FeatureFlagConditionGroupSchemaApi)
            .optional()
            .describe(
                "Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the \*\*exclusion\*\* percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person\/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout."
            ),
        created_by: UserBasicApi.optional(),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
    })
    .describe('A holdout group — a stable slice of users excluded from experiment exposure.')

export type PatchedExperimentHoldoutApi = zod.input<typeof PatchedExperimentHoldoutApi>
export type PatchedExperimentHoldoutApiOutput = zod.output<typeof PatchedExperimentHoldoutApi>

export const experimentSavedMetricApiNameMax = 400

export const experimentSavedMetricApiDescriptionMax = 400

export const ExperimentSavedMetricApi = zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .max(experimentSavedMetricApiNameMax)
            .describe('Name of the shared metric. Must be unique within the project (case-insensitive).'),
        description: zod
            .string()
            .max(experimentSavedMetricApiDescriptionMax)
            .nullish()
            .describe('Short description of what the metric measures.'),
        query: zod
            .unknown()
            .describe(
                "ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics."
            ),
        created_by: UserBasicApi,
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        tags: zod.array(zod.unknown()).optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type ExperimentSavedMetricApi = zod.input<typeof ExperimentSavedMetricApi>
export type ExperimentSavedMetricApiOutput = zod.output<typeof ExperimentSavedMetricApi>

export const PaginatedExperimentSavedMetricListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ExperimentSavedMetricApi),
})

export type PaginatedExperimentSavedMetricListApi = zod.input<typeof PaginatedExperimentSavedMetricListApi>
export type PaginatedExperimentSavedMetricListApiOutput = zod.output<typeof PaginatedExperimentSavedMetricListApi>

export const patchedExperimentSavedMetricApiNameMax = 400

export const patchedExperimentSavedMetricApiDescriptionMax = 400

export const PatchedExperimentSavedMetricApi = zod
    .object({
        id: zod.number().optional(),
        name: zod
            .string()
            .max(patchedExperimentSavedMetricApiNameMax)
            .optional()
            .describe('Name of the shared metric. Must be unique within the project (case-insensitive).'),
        description: zod
            .string()
            .max(patchedExperimentSavedMetricApiDescriptionMax)
            .nullish()
            .describe('Short description of what the metric measures.'),
        query: zod
            .unknown()
            .optional()
            .describe(
                "ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics."
            ),
        created_by: UserBasicApi.optional(),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        tags: zod.array(zod.unknown()).optional(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type PatchedExperimentSavedMetricApi = zod.input<typeof PatchedExperimentSavedMetricApi>
export type PatchedExperimentSavedMetricApiOutput = zod.output<typeof PatchedExperimentSavedMetricApi>

export const EvaluationRuntimeEnumApi = zod
    .enum(['server', 'client', 'all'])
    .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All')

export type EvaluationRuntimeEnumApi = zod.input<typeof EvaluationRuntimeEnumApi>
export type EvaluationRuntimeEnumApiOutput = zod.output<typeof EvaluationRuntimeEnumApi>

export const BucketingIdentifierEnumApi = zod
    .enum(['distinct_id', 'device_id'])
    .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID')

export type BucketingIdentifierEnumApi = zod.input<typeof BucketingIdentifierEnumApi>
export type BucketingIdentifierEnumApiOutput = zod.output<typeof BucketingIdentifierEnumApi>

export const minimalFeatureFlagApiKeyMax = 400

export const minimalFeatureFlagApiVersionMin = -2147483648
export const minimalFeatureFlagApiVersionMax = 2147483647

export const MinimalFeatureFlagApi = zod.object({
    id: zod.number(),
    team_id: zod.number(),
    name: zod.string().optional(),
    key: zod.string().max(minimalFeatureFlagApiKeyMax),
    filters: zod.record(zod.string(), zod.unknown()).optional(),
    deleted: zod.boolean().optional(),
    active: zod.boolean().optional(),
    ensure_experience_continuity: zod.boolean().nullish(),
    version: zod.number().min(minimalFeatureFlagApiVersionMin).max(minimalFeatureFlagApiVersionMax).nullish(),
    evaluation_runtime: zod
        .union([EvaluationRuntimeEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
        ),
    bucketing_identifier: zod
        .union([BucketingIdentifierEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
        ),
    evaluation_contexts: zod.array(zod.string()),
})

export type MinimalFeatureFlagApi = zod.input<typeof MinimalFeatureFlagApi>
export type MinimalFeatureFlagApiOutput = zod.output<typeof MinimalFeatureFlagApi>

export const ExperimentParametersApi = zod.object({
    minimum_detectable_effect: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
        ),
    variant_notes: zod
        .union([zod.record(zod.string(), zod.string()), zod.null()])
        .optional()
        .describe(
            'Free-text notes per variant, keyed by variant key. Use to document what each variant does or its reroute URL.'
        ),
})

export type ExperimentParametersApi = zod.input<typeof ExperimentParametersApi>
export type ExperimentParametersApiOutput = zod.output<typeof ExperimentParametersApi>

export const ConversionRateInputTypeApi = zod.enum(['manual', 'automatic'])

export type ConversionRateInputTypeApi = zod.input<typeof ConversionRateInputTypeApi>
export type ConversionRateInputTypeApiOutput = zod.output<typeof ConversionRateInputTypeApi>

export const ManualMetricTypeApi = zod.enum(['funnel', 'mean_count', 'mean_sum_or_avg'])

export type ManualMetricTypeApi = zod.input<typeof ManualMetricTypeApi>
export type ManualMetricTypeApiOutput = zod.output<typeof ManualMetricTypeApi>

export const ExperimentExposureEstimateConfigApi = zod.object({
    conversionRateInputType: ConversionRateInputTypeApi.describe(
        "\'manual\' when the baseline value and exposure rate were entered by hand, \'automatic\' when derived from live experiment data."
    ),
    manualBaselineValue: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Manually entered baseline metric value (a conversion percentage for funnel metrics). Only used in manual mode.'
        ),
    manualExposureRate: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Manually entered estimate of users exposed to the experiment per day. Only used in manual mode.'),
    manualMetricType: zod
        .union([ManualMetricTypeApi, zod.null()])
        .optional()
        .describe('Metric type the manual baseline value refers to. Only used in manual mode.'),
})

export type ExperimentExposureEstimateConfigApi = zod.input<typeof ExperimentExposureEstimateConfigApi>
export type ExperimentExposureEstimateConfigApiOutput = zod.output<typeof ExperimentExposureEstimateConfigApi>

export const ExperimentRunningTimeCalculationApi = zod.object({
    exposure_estimate_config: zod
        .union([ExperimentExposureEstimateConfigApi, zod.null()])
        .optional()
        .describe(
            'How the exposure estimate is configured: manual user-entered values or automatic from live experiment data.'
        ),
    minimum_detectable_effect: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes.'),
    recommended_running_time: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Estimated number of days needed to reach the recommended sample size.'),
    recommended_sample_size: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Recommended number of exposed users needed for statistical significance.'),
})

export type ExperimentRunningTimeCalculationApi = zod.input<typeof ExperimentRunningTimeCalculationApi>
export type ExperimentRunningTimeCalculationApiOutput = zod.output<typeof ExperimentRunningTimeCalculationApi>

export const ExperimentTypeEnumApi = zod.enum(['web', 'product']).describe('\* `web` - web\n\* `product` - product')

export type ExperimentTypeEnumApi = zod.input<typeof ExperimentTypeEnumApi>
export type ExperimentTypeEnumApiOutput = zod.output<typeof ExperimentTypeEnumApi>

export const ConclusionEnumApi = zod
    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
    .describe(
        '\* `won` - won\n\* `lost` - lost\n\* `inconclusive` - inconclusive\n\* `stopped_early` - stopped_early\n\* `invalid` - invalid'
    )

export type ConclusionEnumApi = zod.input<typeof ConclusionEnumApi>
export type ConclusionEnumApiOutput = zod.output<typeof ConclusionEnumApi>

export const ExperimentStatusEnumApi = zod.enum(['draft', 'running', 'paused', 'exposure_frozen', 'stopped'])

export type ExperimentStatusEnumApi = zod.input<typeof ExperimentStatusEnumApi>
export type ExperimentStatusEnumApiOutput = zod.output<typeof ExperimentStatusEnumApi>

export const experimentBasicApiNameMax = 400

export const experimentBasicApiDescriptionMax = 3000

export const experimentBasicApiArchivedDefault = false
export const experimentBasicApiConclusionCommentMax = 4000

export const ExperimentBasicApi = zod
    .object({
        id: zod.number(),
        name: zod.string().max(experimentBasicApiNameMax).describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentBasicApiDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        feature_flag_key: zod
            .string()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible."
            ),
        feature_flag: MinimalFeatureFlagApi,
        holdout: ExperimentHoldoutApi,
        exposure_cohort: zod.number().nullable(),
        parameters: zod
            .union([ExperimentParametersApi, zod.null()])
            .optional()
            .describe(
                "Experiment parameters JSON. Supported keys include `custom_exposure_filter` and `variant_notes` (free-text notes per variant, keyed by variant key). Flag config (variants, rollout, aggregation, payloads, experience continuity) belongs on the `feature_flag` object; send it there. For backward compatibility, config still sent through these deprecated keys is copied onto the linked flag rather than rejected, and reads project the flag's current config back into this field. Excluded variants live on the top-level `excluded_variants` field, not here."
            ),
        running_time_calculation: zod
            .union([ExperimentRunningTimeCalculationApi, zod.null()])
            .optional()
            .describe(
                'Running-time calculator state: `minimum_detectable_effect`, `recommended_running_time`, `recommended_sample_size`, and `exposure_estimate_config`. Canonical home for these keys, which historically lived in `parameters`.'
            ),
        excluded_variants: zod
            .array(zod.string())
            .nullish()
            .describe(
                'Variant keys to exclude from metric result calculations. Excluded variants are still served to users but omitted from statistical analysis. The baseline variant and holdout pseudo-variants cannot be excluded. Canonical home for what historically lived in `parameters.excluded_variants`.'
            ),
        archived: zod
            .boolean()
            .default(experimentBasicApiArchivedDefault)
            .describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        created_by: UserBasicApi,
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        type: zod
            .union([ExperimentTypeEnumApi, zod.null()])
            .optional()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend\/API changes.\n\n\* `web` - web\n\* `product` - product'
            ),
        conclusion: zod
            .union([ConclusionEnumApi, zod.null()])
            .optional()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n\* `won` - won\n\* `lost` - lost\n\* `inconclusive` - inconclusive\n\* `stopped_early` - stopped_early\n\* `invalid` - invalid'
            ),
        conclusion_comment: zod
            .string()
            .max(experimentBasicApiConclusionCommentMax)
            .nullish()
            .describe('Comment about the experiment conclusion.'),
        status: ExperimentStatusEnumApi.describe(
            "Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'exposure_frozen' (running with enrollment frozen to the already-exposed cohort while metrics keep flowing — virtual state derived from the flag's release groups, not stored), 'stopped' (ended)."
        ),
        is_legacy: zod
            .boolean()
            .describe(
                "Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support them, such as duplicate and copy-to-project."
            ),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe(
        "Lightweight, read-only serializer for the experiment list endpoint.\n\nThe list view (and the MCP list tool) render only the scalar and feature-flag fields\nshared via ``ExperimentBaseSerializer`` — never the metric definitions. Omitting\n``metrics``\/``metrics_secondary``\/``saved_metrics`` lets the list query defer the large\nJSON columns and skip the saved-metric prefetch plus per-row fingerprinting; that work\nbelongs to the detail response served by ``ExperimentSerializer``.\n\nBecause the metric fields, the write-side machinery, and the action-name-refreshing\n``to_representation`` all live on ``ExperimentSerializer`` rather than the shared base,\nthis serializer needs no overrides: it gets DRF's default ``get_fields`` (no write-only\n``holdout_id`` to configure), default ``to_representation`` (no metrics to normalize), and\na plain ``ListSerializer`` that never touches the deferred columns. See\n``EnterpriseExperimentsViewSet.safely_get_queryset``."
    )

export type ExperimentBasicApi = zod.input<typeof ExperimentBasicApi>
export type ExperimentBasicApiOutput = zod.output<typeof ExperimentBasicApi>

export const PaginatedExperimentBasicListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ExperimentBasicApi),
})

export type PaginatedExperimentBasicListApi = zod.input<typeof PaginatedExperimentBasicListApi>
export type PaginatedExperimentBasicListApiOutput = zod.output<typeof PaginatedExperimentBasicListApi>

export const ExperimentWriteApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentWriteApi = zod.input<typeof ExperimentWriteApi>
export type ExperimentWriteApiOutput = zod.output<typeof ExperimentWriteApi>

export const ExperimentApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentApi = zod.input<typeof ExperimentApi>
export type ExperimentApiOutput = zod.output<typeof ExperimentApi>

export const PatchedExperimentWriteApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PatchedExperimentWriteApi = zod.input<typeof PatchedExperimentWriteApi>
export type PatchedExperimentWriteApiOutput = zod.output<typeof PatchedExperimentWriteApi>

export const ChangeApi = zod.object({
    type: zod.string(),
    action: zod.string(),
    field: zod.string(),
    before: zod.unknown(),
    after: zod.unknown(),
})

export type ChangeApi = zod.input<typeof ChangeApi>
export type ChangeApiOutput = zod.output<typeof ChangeApi>

export const MergeApi = zod.object({
    type: zod.string(),
    source: zod.unknown(),
    target: zod.unknown(),
})

export type MergeApi = zod.input<typeof MergeApi>
export type MergeApiOutput = zod.output<typeof MergeApi>

export const TriggerApi = zod.object({
    job_type: zod.string(),
    job_id: zod.string(),
    payload: zod.unknown(),
})

export type TriggerApi = zod.input<typeof TriggerApi>
export type TriggerApiOutput = zod.output<typeof TriggerApi>

export const DetailApi = zod.object({
    id: zod.string(),
    changes: zod.array(ChangeApi).optional(),
    merge: MergeApi.optional(),
    trigger: TriggerApi.optional(),
    name: zod.string(),
    short_id: zod.string(),
    type: zod.string(),
})

export type DetailApi = zod.input<typeof DetailApi>
export type DetailApiOutput = zod.output<typeof DetailApi>

export const ActivityLogEntryApi = zod.object({
    id: zod.uuid(),
    user: zod.looseObject({}).nullable(),
    activity: zod.string(),
    scope: zod.string(),
    item_id: zod.string(),
    detail: DetailApi.optional(),
    created_at: zod.iso.datetime({ offset: true }),
    is_system: zod.boolean().describe('Whether the activity was performed by the system rather than a user.'),
    was_impersonated: zod.boolean().describe('Whether the acting user was being impersonated by PostHog staff.'),
    client: zod
        .string()
        .nullable()
        .describe(
            "API client that triggered the activity, from the x-posthog-client request header (e.g. 'mcp'). Null for requests that did not send the header."
        ),
})

export type ActivityLogEntryApi = zod.input<typeof ActivityLogEntryApi>
export type ActivityLogEntryApiOutput = zod.output<typeof ActivityLogEntryApi>

export const ActivityLogPaginatedResponseApi = zod
    .object({
        results: zod.array(ActivityLogEntryApi),
        next: zod.url().nullable(),
        previous: zod.url().nullable(),
        total_count: zod.number(),
    })
    .describe('Response shape for paginated activity log endpoints.')

export type ActivityLogPaginatedResponseApi = zod.input<typeof ActivityLogPaginatedResponseApi>
export type ActivityLogPaginatedResponseApiOutput = zod.output<typeof ActivityLogPaginatedResponseApi>

export const archiveExperimentApiDisableFeatureFlagDefault = false

export const ArchiveExperimentApi = zod.object({
    disable_feature_flag: zod
        .boolean()
        .default(archiveExperimentApiDisableFeatureFlagDefault)
        .describe(
            'When the linked feature flag is still enabled, also disable and archive it along with the experiment. Has no effect if the flag is already disabled (it is archived either way).'
        ),
})

export type ArchiveExperimentApi = zod.input<typeof ArchiveExperimentApi>
export type ArchiveExperimentApiOutput = zod.output<typeof ArchiveExperimentApi>

export const CopyExperimentToProjectApi = zod.object({
    target_team_id: zod.number().describe('The team ID to copy the experiment to.'),
    feature_flag_key: zod.string().optional().describe('Optional feature flag key to use in the destination team.'),
    name: zod.string().optional().describe('Optional name for the copied experiment.'),
})

export type CopyExperimentToProjectApi = zod.input<typeof CopyExperimentToProjectApi>
export type CopyExperimentToProjectApiOutput = zod.output<typeof CopyExperimentToProjectApi>

export const endExperimentApiConclusionCommentMax = 4000

export const endExperimentApiOpenCleanupPrDefault = false
export const endExperimentApiRepositoryMax = 255

export const EndExperimentApi = zod.object({
    conclusion: zod
        .union([ConclusionEnumApi, zod.null()])
        .optional()
        .describe(
            'The conclusion of the experiment.\n\n\* `won` - won\n\* `lost` - lost\n\* `inconclusive` - inconclusive\n\* `stopped_early` - stopped_early\n\* `invalid` - invalid'
        ),
    conclusion_comment: zod
        .string()
        .max(endExperimentApiConclusionCommentMax)
        .nullish()
        .describe('Optional comment about the experiment conclusion.'),
    open_cleanup_pr: zod
        .boolean()
        .default(endExperimentApiOpenCleanupPrDefault)
        .describe(
            "When true, open a draft pull request that removes the experiment's feature-flag code from the linked repository. Requires the requesting user to have access to PostHog Desktop (403 otherwise). Only acts for allowlisted teams; ignored otherwise."
        ),
    repository: zod
        .string()
        .max(endExperimentApiRepositoryMax)
        .nullish()
        .describe(
            "GitHub repository to open the cleanup pull request in, in `organization\/repository` format. Only used when open_cleanup_pr is true. It must be one of the team's connected repositories (see the flag_cleanup_target action); it is then saved as the experiment's repository. When omitted, the experiment's saved repository or the team's only connected repository is used."
        ),
})

export type EndExperimentApi = zod.input<typeof EndExperimentApi>
export type EndExperimentApiOutput = zod.output<typeof EndExperimentApi>

export const ExperimentFlagCleanupTargetSourceEnumApi = zod
    .enum(['explicit', 'single_repo', 'ambiguous', 'no_integration'])
    .describe(
        '\* `explicit` - explicit\n\* `single_repo` - single_repo\n\* `ambiguous` - ambiguous\n\* `no_integration` - no_integration'
    )

export type ExperimentFlagCleanupTargetSourceEnumApi = zod.input<typeof ExperimentFlagCleanupTargetSourceEnumApi>
export type ExperimentFlagCleanupTargetSourceEnumApiOutput = zod.output<typeof ExperimentFlagCleanupTargetSourceEnumApi>

export const ExperimentFlagCleanupTargetApi = zod.object({
    repository: zod
        .string()
        .nullable()
        .describe('Repository a flag-cleanup pull request would be opened in, or null when none can be determined.'),
    source: ExperimentFlagCleanupTargetSourceEnumApi.describe(
        "How the repository was determined: `explicit` (saved on the experiment), `single_repo` (the team's only connected repository), `ambiguous` (several connected repositories and none saved — pass one via repository on end\/ship_variant), or `no_integration` (no GitHub integration or no connected repositories, so no cleanup PR can be opened).\n\n\* `explicit` - explicit\n\* `single_repo` - single_repo\n\* `ambiguous` - ambiguous\n\* `no_integration` - no_integration"
    ),
    candidates: zod
        .array(zod.string())
        .describe("Repositories connected to the team's GitHub integration, to choose a target from."),
})

export type ExperimentFlagCleanupTargetApi = zod.input<typeof ExperimentFlagCleanupTargetApi>
export type ExperimentFlagCleanupTargetApiOutput = zod.output<typeof ExperimentFlagCleanupTargetApi>

export const RunStatusEnumApi = zod
    .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
    .describe(
        '\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
    )

export type RunStatusEnumApi = zod.input<typeof RunStatusEnumApi>
export type RunStatusEnumApiOutput = zod.output<typeof RunStatusEnumApi>

export const ExperimentFlagCleanupTaskApi = zod.object({
    task_id: zod.uuid().describe('ID of the flag-cleanup Desktop task.'),
    run_status: RunStatusEnumApi.describe(
        "Status of the task's latest run.\n\n\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled"
    ),
    is_terminal: zod.boolean().describe('Whether the run has finished (successfully or not). Stop polling once true.'),
    pr_url: zod.string().nullable().describe('URL of the pull request the task opened, when it opened one.'),
    can_view_task: zod
        .boolean()
        .describe(
            'Whether the requesting user can open the task in PostHog Desktop. Cleanup tasks are visible to their creator only, so other viewers should not be shown a task link.'
        ),
})

export type ExperimentFlagCleanupTaskApi = zod.input<typeof ExperimentFlagCleanupTaskApi>
export type ExperimentFlagCleanupTaskApiOutput = zod.output<typeof ExperimentFlagCleanupTaskApi>

export const TriggerEnumApi = zod
    .enum([
        'manual',
        'agent_mcp',
        'cold_run',
        'stale_refresh',
        'auto_refresh',
        'config_change',
        'experiment_launch',
        'experiment_stop',
        'experiment_update',
    ])
    .describe(
        '\* `manual` - Manual\n\* `agent_mcp` - Agent (MCP)\n\* `cold_run` - Cold Run\n\* `stale_refresh` - Stale Refresh\n\* `auto_refresh` - Auto Refresh\n\* `config_change` - Config Change\n\* `experiment_launch` - Experiment Launch\n\* `experiment_stop` - Experiment Stop\n\* `experiment_update` - Experiment Update'
    )

export type TriggerEnumApi = zod.input<typeof TriggerEnumApi>
export type TriggerEnumApiOutput = zod.output<typeof TriggerEnumApi>

export const recalculateMetricsRequestApiTriggerDefault = `manual`

export const RecalculateMetricsRequestApi = zod
    .object({
        trigger: TriggerEnumApi.default(recalculateMetricsRequestApiTriggerDefault).describe(
            'What triggered this recalculation (manual is the default for user-initiated runs)\n\n\* `manual` - Manual\n\* `agent_mcp` - Agent (MCP)\n\* `cold_run` - Cold Run\n\* `stale_refresh` - Stale Refresh\n\* `auto_refresh` - Auto Refresh\n\* `config_change` - Config Change\n\* `experiment_launch` - Experiment Launch\n\* `experiment_stop` - Experiment Stop\n\* `experiment_update` - Experiment Update'
        ),
    })
    .describe('Request body for triggering a metrics recalculation.')

export type RecalculateMetricsRequestApi = zod.input<typeof RecalculateMetricsRequestApi>
export type RecalculateMetricsRequestApiOutput = zod.output<typeof RecalculateMetricsRequestApi>

export const MetricsRecalculationStatusEnumApi = zod
    .enum(['pending', 'in_progress', 'completed', 'failed'])
    .describe(
        '\* `pending` - Pending\n\* `in_progress` - In Progress\n\* `completed` - Completed\n\* `failed` - Failed'
    )

export type MetricsRecalculationStatusEnumApi = zod.input<typeof MetricsRecalculationStatusEnumApi>
export type MetricsRecalculationStatusEnumApiOutput = zod.output<typeof MetricsRecalculationStatusEnumApi>

export const ActiveRecalculationRunApi = zod
    .object({
        id: zod.uuid().describe('Identifier of the run that is still executing'),
        status: MetricsRecalculationStatusEnumApi.describe(
            'Status of the executing run (pending or in_progress)\n\n\* `pending` - Pending\n\* `in_progress` - In Progress\n\* `completed` - Completed\n\* `failed` - Failed'
        ),
    })
    .describe('Pointer to a recalculation run that is still executing, surfaced alongside the latest terminal results.')

export type ActiveRecalculationRunApi = zod.input<typeof ActiveRecalculationRunApi>
export type ActiveRecalculationRunApiOutput = zod.output<typeof ActiveRecalculationRunApi>

export const ResultSourceEnumApi = zod
    .enum(['recalculation', 'timeseries_fallback'])
    .describe('\* `recalculation` - recalculation\n\* `timeseries_fallback` - timeseries_fallback')

export type ResultSourceEnumApi = zod.input<typeof ResultSourceEnumApi>
export type ResultSourceEnumApiOutput = zod.output<typeof ResultSourceEnumApi>

export const MetricRecalculationResultStatusEnumApi = zod
    .enum(['pending', 'completed', 'failed'])
    .describe('\* `pending` - pending\n\* `completed` - completed\n\* `failed` - failed')

export type MetricRecalculationResultStatusEnumApi = zod.input<typeof MetricRecalculationResultStatusEnumApi>
export type MetricRecalculationResultStatusEnumApiOutput = zod.output<typeof MetricRecalculationResultStatusEnumApi>

export const MetricRecalculationResultApi = zod
    .object({
        metric_uuid: zod.string().describe('UUID of the metric this result belongs to'),
        status: MetricRecalculationResultStatusEnumApi.describe(
            "Status of this metric's calculation in the run\n\n\* `pending` - pending\n\* `completed` - completed\n\* `failed` - failed"
        ),
        result: zod
            .unknown()
            .describe(
                'The computed metric result (ExperimentQueryResponse shape); null when status is pending or failed'
            ),
        error_message: zod.string().nullable().describe('Error message when status is failed; otherwise null'),
    })
    .describe("One metric's recalculated result row, read back from ExperimentMetricResult.")

export type MetricRecalculationResultApi = zod.input<typeof MetricRecalculationResultApi>
export type MetricRecalculationResultApiOutput = zod.output<typeof MetricRecalculationResultApi>

export const experimentMetricsRecalculationApiResultSourceDefault = `recalculation`

export const ExperimentMetricsRecalculationApi = zod
    .object({
        id: zod.uuid().describe('Unique identifier for this recalculation job'),
        experiment_id: zod.number().describe('ID of the experiment being recalculated'),
        status: MetricsRecalculationStatusEnumApi.describe(
            'Current status of the recalculation job\n\n\* `pending` - Pending\n\* `in_progress` - In Progress\n\* `completed` - Completed\n\* `failed` - Failed'
        ),
        total_metrics: zod.number().describe('Total number of metrics to recalculate'),
        completed_metrics: zod
            .number()
            .describe('Number of metrics with a COMPLETED result row in this run (derived, not stored)'),
        failed_metrics: zod
            .number()
            .describe(
                'Number of failed metrics in this run (derived): FAILED result rows plus discovery-step failures that never made it to a result row'
            ),
        metric_errors: zod.unknown().describe('Map of metric_uuid to error details'),
        metric_retries: zod
            .unknown()
            .describe(
                'Transient retry state per metric_uuid: {attempt, max_attempts, error_type, message, next_retry_at}. message is a user-safe description of the error that triggered the retry. Present only while a metric is between failed attempts; cleared when it succeeds or fails terminally, so treat entries for metrics that already have a result as stale.'
            ),
        trigger: TriggerEnumApi.describe(
            'What triggered this recalculation\n\n\* `manual` - Manual\n\* `agent_mcp` - Agent (MCP)\n\* `cold_run` - Cold Run\n\* `stale_refresh` - Stale Refresh\n\* `auto_refresh` - Auto Refresh\n\* `config_change` - Config Change\n\* `experiment_launch` - Experiment Launch\n\* `experiment_stop` - Experiment Stop\n\* `experiment_update` - Experiment Update'
        ),
        created_at: zod.iso.datetime({ offset: true }).describe('When the job was created'),
        started_at: zod.iso.datetime({ offset: true }).nullable().describe('When processing started'),
        completed_at: zod.iso.datetime({ offset: true }).nullable().describe('When processing completed'),
        query_to: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe(
                'Upper time bound the metrics in this run were calculated against (the data freshness cutoff). Shared by every metric in the run; null until processing starts'
            ),
        is_existing: zod.boolean().describe('True if returning an existing job rather than a newly created one'),
        active_run: zod
            .union([ActiveRecalculationRunApi, zod.null()])
            .describe('Run currently executing for this experiment, if any; poll it by id for live progress'),
        result_source: ResultSourceEnumApi.default(experimentMetricsRecalculationApiResultSourceDefault).describe(
            "Where these results came from: 'recalculation' for a real metrics-recalculation run, 'timeseries_fallback' for a cold-start placeholder built from the latest daily timeseries data.\n\n\* `recalculation` - recalculation\n\* `timeseries_fallback` - timeseries_fallback"
        ),
        results: zod
            .array(MetricRecalculationResultApi)
            .describe("Per-metric results computed by this run, scoped by the run's recalc fingerprint"),
        rows_read: zod
            .number()
            .nullish()
            .describe(
                "Rows read by the run's metric queries so far, both finished and currently running. Cumulative and roughly monotonic across the run; the primary live progress signal"
            ),
        estimated_rows_total: zod
            .number()
            .nullish()
            .describe(
                "ClickHouse's total_rows_approx across running queries plus the final read_rows of finished ones. A soft ceiling revised mid-scan, so it can exceed or trail rows_read; treat rows_read as the reliable signal"
            ),
    })
    .describe('Serializer for metrics recalculation status responses.')

export type ExperimentMetricsRecalculationApi = zod.input<typeof ExperimentMetricsRecalculationApi>
export type ExperimentMetricsRecalculationApiOutput = zod.output<typeof ExperimentMetricsRecalculationApi>

export const shipVariantApiConclusionCommentMax = 4000

export const shipVariantApiOpenCleanupPrDefault = false
export const shipVariantApiRepositoryMax = 255

export const shipVariantApiReleaseToEveryoneDefault = false

export const ShipVariantApi = zod.object({
    conclusion: zod
        .union([ConclusionEnumApi, zod.null()])
        .optional()
        .describe(
            'The conclusion of the experiment.\n\n\* `won` - won\n\* `lost` - lost\n\* `inconclusive` - inconclusive\n\* `stopped_early` - stopped_early\n\* `invalid` - invalid'
        ),
    conclusion_comment: zod
        .string()
        .max(shipVariantApiConclusionCommentMax)
        .nullish()
        .describe('Optional comment about the experiment conclusion.'),
    open_cleanup_pr: zod
        .boolean()
        .default(shipVariantApiOpenCleanupPrDefault)
        .describe(
            "When true, open a draft pull request that removes the experiment's feature-flag code from the linked repository. Requires the requesting user to have access to PostHog Desktop (403 otherwise). Only acts for allowlisted teams; ignored otherwise."
        ),
    repository: zod
        .string()
        .max(shipVariantApiRepositoryMax)
        .nullish()
        .describe(
            "GitHub repository to open the cleanup pull request in, in `organization\/repository` format. Only used when open_cleanup_pr is true. It must be one of the team's connected repositories (see the flag_cleanup_target action); it is then saved as the experiment's repository. When omitted, the experiment's saved repository or the team's only connected repository is used."
        ),
    variant_key: zod.string().describe('The key of the variant to ship.'),
    release_to_everyone: zod
        .boolean()
        .default(shipVariantApiReleaseToEveryoneDefault)
        .describe(
            'If true, prepend a release condition to the feature flag that rolls the variant out to 100% of users, overriding any existing release conditions on the flag. If false (default), only update the variant distribution — existing release conditions are preserved and the variant is served only to users who already match them.'
        ),
})

export type ShipVariantApi = zod.input<typeof ShipVariantApi>
export type ShipVariantApiOutput = zod.output<typeof ShipVariantApi>

export const MetricTypeEnumApi = zod
    .enum(['funnel', 'mean_count', 'mean_sum_or_avg', 'ratio', 'retention'])
    .describe(
        '\* `funnel` - funnel\n\* `mean_count` - mean_count\n\* `mean_sum_or_avg` - mean_sum_or_avg\n\* `ratio` - ratio\n\* `retention` - retention'
    )

export type MetricTypeEnumApi = zod.input<typeof MetricTypeEnumApi>
export type MetricTypeEnumApiOutput = zod.output<typeof MetricTypeEnumApi>

export const runningTimeBaselineStatsApiNumberOfSamplesMin = 0

export const runningTimeBaselineStatsApiSumSquaresDefault = 0

export const RunningTimeBaselineStatsApi = zod
    .object({
        number_of_samples: zod
            .number()
            .min(runningTimeBaselineStatsApiNumberOfSamplesMin)
            .describe('Number of control-group samples (users\/units) observed.'),
        sum: zod
            .number()
            .describe('Sum of the metric values across the control group (for funnels, the numerator\/conversions).'),
        sum_squares: zod
            .number()
            .default(runningTimeBaselineStatsApiSumSquaresDefault)
            .describe('Sum of squared metric values. Required for ratio\/retention variance.'),
        denominator_sum: zod
            .number()
            .nullish()
            .describe('Sum of the denominator values. Required for ratio\/retention metrics.'),
        denominator_sum_squares: zod
            .number()
            .nullish()
            .describe('Sum of squared denominator values (ratio\/retention variance).'),
        numerator_denominator_sum_product: zod
            .number()
            .nullish()
            .describe('Sum of numerator×denominator products, used for the delta-method covariance term.'),
        step_counts: zod
            .array(zod.number())
            .optional()
            .describe('Per-step counts for funnel metrics; the last entry is the final-step count.'),
    })
    .describe(
        'Raw control-group statistics the calculator uses to derive a baseline value and variance.\n\nSupply this when you want the server to compute the baseline value and (for ratio\/retention)\nthe delta-method variance, instead of passing `baseline_value`\/`variance` directly.'
    )

export type RunningTimeBaselineStatsApi = zod.input<typeof RunningTimeBaselineStatsApi>
export type RunningTimeBaselineStatsApiOutput = zod.output<typeof RunningTimeBaselineStatsApi>

export const runningTimeCalculationInputApiMinimumDetectableEffectMin = 0

export const runningTimeCalculationInputApiNumberOfVariantsDefault = 2
export const runningTimeCalculationInputApiNumberOfVariantsMin = 2

export const runningTimeCalculationInputApiExposureRatePerDayMin = 0

export const RunningTimeCalculationInputApi = zod
    .object({
        metric_type: MetricTypeEnumApi.describe(
            "Metric type to size for. 'funnel' for conversion rates, 'mean_count' for event counts per user, 'mean_sum_or_avg' for summed property values per user, 'ratio' and 'retention' for ratio-style metrics (both require baseline_stats or an explicit variance).\n\n\* `funnel` - funnel\n\* `mean_count` - mean_count\n\* `mean_sum_or_avg` - mean_sum_or_avg\n\* `ratio` - ratio\n\* `retention` - retention"
        ),
        minimum_detectable_effect: zod
            .number()
            .min(runningTimeCalculationInputApiMinimumDetectableEffectMin)
            .describe('Smallest relative change to detect, as a percentage (e.g. 5 means a 5% lift). Must be > 0.'),
        number_of_variants: zod
            .number()
            .min(runningTimeCalculationInputApiNumberOfVariantsMin)
            .default(runningTimeCalculationInputApiNumberOfVariantsDefault)
            .describe('Total number of variants including control (default 2).'),
        exposure_rate_per_day: zod
            .number()
            .min(runningTimeCalculationInputApiExposureRatePerDayMin)
            .nullish()
            .describe('Expected exposures per day. When provided, the response includes the recommended running time.'),
        baseline_value: zod
            .number()
            .nullish()
            .describe(
                'Baseline metric value: conversion rate as a fraction 0-1 (funnel), average per user (mean), or the ratio (ratio\/retention). Provide this or baseline_stats.'
            ),
        variance: zod
            .number()
            .nullish()
            .describe(
                'Pre-computed variance for ratio\/retention metrics. Provide this or baseline_stats when metric_type is ratio\/retention and baseline_value is given directly.'
            ),
        baseline_stats: zod
            .union([RunningTimeBaselineStatsApi, zod.null()])
            .optional()
            .describe('Raw control-group statistics. When provided, the server derives baseline_value and variance.'),
    })
    .describe('Inputs for estimating the recommended sample size and running time of an experiment.')

export type RunningTimeCalculationInputApi = zod.input<typeof RunningTimeCalculationInputApi>
export type RunningTimeCalculationInputApiOutput = zod.output<typeof RunningTimeCalculationInputApi>

export const RunningTimeCalculationResultApi = zod
    .object({
        baseline_value: zod
            .number()
            .nullable()
            .describe('Baseline metric value used in the calculation (echoed or derived from stats).'),
        variance: zod
            .number()
            .nullable()
            .describe('Variance used in the calculation; null for funnel metrics (implicit in p(1-p)).'),
        recommended_sample_size: zod
            .number()
            .nullable()
            .describe('Total recommended sample size across all variants. Null if inputs are insufficient.'),
        recommended_running_time_days: zod
            .number()
            .nullable()
            .describe(
                'Estimated days to reach the recommended sample size. Null when exposure_rate_per_day is omitted.'
            ),
    })
    .describe('Estimated sample size and running time for the given inputs.')

export type RunningTimeCalculationResultApi = zod.input<typeof RunningTimeCalculationResultApi>
export type RunningTimeCalculationResultApiOutput = zod.output<typeof RunningTimeCalculationResultApi>

export const TemplatesEnumApi = zod
    .enum(['cost', 'latency', 'eval_pass_rate'])
    .describe('\* `cost` - cost\n\* `latency` - latency\n\* `eval_pass_rate` - eval_pass_rate')

export type TemplatesEnumApi = zod.input<typeof TemplatesEnumApi>
export type TemplatesEnumApiOutput = zod.output<typeof TemplatesEnumApi>

export const createFromPromptInputApiVersionsMin = 2
export const createFromPromptInputApiVersionsMax = 10

export const createFromPromptInputApiTemplatesMax = 3

export const CreateFromPromptInputApi = zod.object({
    prompt_name: zod
        .string()
        .describe('The name of the LLM prompt to experiment on. Must already exist for this team.'),
    versions: zod
        .array(zod.number().min(1))
        .min(createFromPromptInputApiVersionsMin)
        .max(createFromPromptInputApiVersionsMax)
        .describe(
            'Ordered list of prompt version numbers to assign to experiment variants. The first entry is the control variant. Must contain between 2 and 10 distinct versions.'
        ),
    templates: zod
        .array(TemplatesEnumApi)
        .min(1)
        .max(createFromPromptInputApiTemplatesMax)
        .describe(
            'One or more metric templates to attach as primary metrics. Each template becomes one metric on the experiment. Allowed values: cost, latency, eval_pass_rate.'
        ),
    name: zod
        .string()
        .optional()
        .describe('Optional experiment name. If omitted, a name is generated from the prompt and versions.'),
    feature_flag_key: zod
        .string()
        .optional()
        .describe('Optional feature flag key. If omitted, a slug is derived from the experiment name.'),
    description: zod.string().optional().describe('Optional experiment description.'),
})

export type CreateFromPromptInputApi = zod.input<typeof CreateFromPromptInputApi>
export type CreateFromPromptInputApiOutput = zod.output<typeof CreateFromPromptInputApi>

export const SourceRoleEnumApi = zod
    .enum(['source', 'step', 'numerator', 'denominator', 'retention_start', 'retention_completion'])
    .describe(
        '\* `source` - source\n\* `step` - step\n\* `numerator` - numerator\n\* `denominator` - denominator\n\* `retention_start` - retention_start\n\* `retention_completion` - retention_completion'
    )

export type SourceRoleEnumApi = zod.input<typeof SourceRoleEnumApi>
export type SourceRoleEnumApiOutput = zod.output<typeof SourceRoleEnumApi>

export const ExperimentSessionMetricSourceHitApi = zod
    .object({
        source_role: SourceRoleEnumApi.describe(
            "What this source means to its metric: 'source' (a mean metric's single event), 'step' (a funnel step, numbered by source_index), 'numerator'\/'denominator' (a ratio metric's two sides), or 'retention_start'\/'retention_completion' (a retention metric's start event and return visit). A hit on one source is not a hit on the metric as the analysis counts it.\n\n\* `source` - source\n\* `step` - step\n\* `numerator` - numerator\n\* `denominator` - denominator\n\* `retention_start` - retention_start\n\* `retention_completion` - retention_completion"
        ),
        source_name: zod.string().describe('Display name of the source event or action.'),
        source_index: zod
            .number()
            .describe(
                "0-based position of this source among all the metric's sources, data-warehouse ones included — so a funnel step keeps its real step number even when an earlier step has no session events."
            ),
        source_total: zod.number().describe('Total number of sources the metric is defined over.'),
        event_count: zod.number().describe('Number of events in the session matching this source.'),
        first_timestamp: zod.iso
            .datetime({ offset: true })
            .describe('Timestamp of the first event in the session matching this source.'),
        timestamps: zod
            .array(zod.iso.datetime({ offset: true }))
            .describe(
                "Ascending timestamps of this source's matching events in the session, capped at the first 50. event_count is the true total, so this list may be shorter — treat these as seek points, not a count."
            ),
    })
    .describe('One event\/action source of a metric with at least one matching event in a session recording.')

export type ExperimentSessionMetricSourceHitApi = zod.input<typeof ExperimentSessionMetricSourceHitApi>
export type ExperimentSessionMetricSourceHitApiOutput = zod.output<typeof ExperimentSessionMetricSourceHitApi>

export const ExperimentSessionMetricHitApi = zod
    .object({
        metric_uuid: zod
            .string()
            .describe('UUID of the experiment metric (inline primary\/secondary or saved) whose events fired.'),
        metric_name: zod
            .string()
            .describe(
                'Display name of the metric, or an event-derived title (matching the experiment UI) when unnamed.'
            ),
        event_count: zod
            .number()
            .describe("Total number of events in the session matching any of the metric's event\/action sources."),
        first_timestamp: zod.iso
            .datetime({ offset: true })
            .describe('Timestamp of the first event in the session matching the metric.'),
        timestamps: zod
            .array(zod.iso.datetime({ offset: true }))
            .describe(
                "Ascending timestamps of the metric's matching events in the session, capped at the first 50. event_count is the true total, so this list may be shorter — treat these as seek points, not a count."
            ),
        sources: zod
            .array(ExperimentSessionMetricSourceHitApi)
            .describe(
                "Which of the metric's sources fired, so a hit reads as 'step 2 of 3' or 'the start event of a retention metric' rather than an unqualified 'this metric happened'. Sources with no matching event are omitted, as is the whole breakdown for metrics beyond the scan's aggregate ceiling. A retention metric whose start and completion are the same event contributes only the start source: the completion would match the identical events and render a duplicate."
            ),
    })
    .describe('One experiment metric with at least one matching event in a session recording.')

export type ExperimentSessionMetricHitApi = zod.input<typeof ExperimentSessionMetricHitApi>
export type ExperimentSessionMetricHitApiOutput = zod.output<typeof ExperimentSessionMetricHitApi>

export const ExperimentSessionContextItemApi = zod
    .object({
        experiment_id: zod.number().describe('ID of the experiment whose feature flag the session saw.'),
        experiment_name: zod.string().describe('Name of the experiment.'),
        flag_key: zod.string().describe("Key of the experiment's feature flag."),
        variant: zod
            .string()
            .describe(
                "Variant the session saw. Taken from the earliest event matching the experiment's exposure criteria when one exists, otherwise from the earliest flag evaluation in the session, otherwise from the $feature\/<key> property stamped on the session's events."
            ),
        variants_seen: zod
            .array(zod.string())
            .describe(
                "All distinct variant values observed for this flag during the session, sorted alphabetically. Only the flag's defined variant keys count; non-enrollment responses (false) are ignored. More than one value means the session saw multiple variants — a signal of multi-exposure bias."
            ),
        multiple_variants: zod.boolean().describe('True when the session saw more than one variant of this flag.'),
        first_exposure_timestamp: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe(
                "Timestamp of the first event in the session matching the experiment's exposure criteria — the default exposure event ($feature_flag_called), or the configured custom event\/action. Null when no event in the session matched the criteria; the variant is then known from flag evaluations or stamped $feature\/<key> properties. Session-scoped: the experiment analysis counts exposure per person across the whole run window, so the person's counted first exposure may lie in an earlier session."
            ),
        experiment_start_date: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the experiment was launched.'),
        experiment_end_date: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the experiment ended. Null while the experiment is still running.'),
        metrics_in_session: zod
            .array(ExperimentSessionMetricHitApi)
            .describe(
                "This experiment's metrics with at least one matching event in the session, sorted by first occurrence. Empty when none of the experiment's metric events fired during the session."
            ),
    })
    .describe('One experiment whose feature flag a session recording saw.')

export type ExperimentSessionContextItemApi = zod.input<typeof ExperimentSessionContextItemApi>
export type ExperimentSessionContextItemApiOutput = zod.output<typeof ExperimentSessionContextItemApi>

export const ExperimentSessionContextResponseApi = zod
    .object({
        session_id: zod.string().describe('ID of the session recording the context was resolved for.'),
        results: zod
            .array(ExperimentSessionContextItemApi)
            .describe(
                "Experiments (and variants) the session saw, sorted by experiment name. Empty when no launched experiment's run window overlaps the recording or no flag data was observed in the session."
            ),
    })
    .describe('Experiment\/variant context for a session recording.')

export type ExperimentSessionContextResponseApi = zod.input<typeof ExperimentSessionContextResponseApi>
export type ExperimentSessionContextResponseApiOutput = zod.output<typeof ExperimentSessionContextResponseApi>

export const experimentSessionContextsRequestApiSessionIdsMax = 20

export const ExperimentSessionContextsRequestApi = zod
    .object({
        session_ids: zod
            .array(zod.string().describe('ID of one session recording.'))
            .min(1)
            .max(experimentSessionContextsRequestApiSessionIdsMax)
            .describe(
                'IDs of the session recordings to resolve experiment context for, at most 20 per request. Duplicates are ignored.'
            ),
    })
    .describe('Request body for the batch session-context endpoint.')

export type ExperimentSessionContextsRequestApi = zod.input<typeof ExperimentSessionContextsRequestApi>
export type ExperimentSessionContextsRequestApiOutput = zod.output<typeof ExperimentSessionContextsRequestApi>

export const ExperimentSessionContextsResponseApi = zod
    .object({
        results: zod
            .array(ExperimentSessionContextResponseApi)
            .describe(
                "Per-session experiment context, in the order the session IDs were requested. Sessions whose recording metadata doesn't exist yet (still ingesting, or unknown to this project) are omitted, as are recordings you don't have access to and sessions beyond the batch's recording-day budget (only the most recent days are computed). Fetch omitted sessions individually via the single-session endpoint."
            ),
    })
    .describe('Experiment\/variant context for a batch of session recordings.')

export type ExperimentSessionContextsResponseApi = zod.input<typeof ExperimentSessionContextsResponseApi>
export type ExperimentSessionContextsResponseApiOutput = zod.output<typeof ExperimentSessionContextsResponseApi>

export const experimentFlagRolloutGroupApiRolloutPercentageMin = 0
export const experimentFlagRolloutGroupApiRolloutPercentageMax = 100

export const experimentFlagRolloutGroupApiPropertiesMax = 0

export const ExperimentFlagRolloutGroupApi = zod
    .object({
        rollout_percentage: zod
            .number()
            .min(experimentFlagRolloutGroupApiRolloutPercentageMin)
            .max(experimentFlagRolloutGroupApiRolloutPercentageMax)
            .nullish()
            .describe('Percentage of users who enter the experiment (0-100).'),
        properties: zod
            .array(zod.unknown())
            .max(experimentFlagRolloutGroupApiPropertiesMax)
            .optional()
            .describe(
                'Must be empty or omitted: release-condition properties are not supported via the experiment input. Edit the feature flag directly for targeting.'
            ),
    })
    .describe(
        'A single release-condition group carrying only the overall rollout percentage, the one\ngroups entry the experiment input applies.'
    )

export type ExperimentFlagRolloutGroupApi = zod.input<typeof ExperimentFlagRolloutGroupApi>
export type ExperimentFlagRolloutGroupApiOutput = zod.output<typeof ExperimentFlagRolloutGroupApi>

export const experimentFlagVariantApiRolloutPercentageMin = 0
export const experimentFlagVariantApiRolloutPercentageMax = 100

export const ExperimentFlagVariantApi = zod
    .object({
        key: zod
            .string()
            .describe(
                "Unique variant key. The baseline defaults to the variant keyed 'control' when present, else the first variant."
            ),
        name: zod.string().optional().describe('Human-readable variant name.'),
        rollout_percentage: zod
            .number()
            .min(experimentFlagVariantApiRolloutPercentageMin)
            .max(experimentFlagVariantApiRolloutPercentageMax)
            .describe('Variant rollout percentage (0-100). Across variants these must sum to 100.'),
    })
    .describe('A single multivariate variant. Extra per-variant keys are dropped.')

export type ExperimentFlagVariantApi = zod.input<typeof ExperimentFlagVariantApi>
export type ExperimentFlagVariantApiOutput = zod.output<typeof ExperimentFlagVariantApi>

export const ExperimentFlagMultivariateApi = zod
    .object({
        variants: zod
            .array(ExperimentFlagVariantApi)
            .describe(
                "Variant definitions (2 to 20). The baseline defaults to the variant keyed 'control' when present, else the first variant."
            ),
    })
    .describe("Multivariate config for the experiment's feature flag.")

export type ExperimentFlagMultivariateApi = zod.input<typeof ExperimentFlagMultivariateApi>
export type ExperimentFlagMultivariateApiOutput = zod.output<typeof ExperimentFlagMultivariateApi>

export const ExperimentFeatureFlagFiltersApi = zod
    .object({
        groups: zod
            .array(ExperimentFlagRolloutGroupApi)
            .optional()
            .describe('Overall rollout as a single group: [{\"properties\": [], \"rollout_percentage\": N}].'),
        multivariate: zod
            .union([ExperimentFlagMultivariateApi, zod.null()])
            .optional()
            .describe('Multivariate variant configuration.'),
        aggregation_group_type_index: zod
            .number()
            .nullish()
            .describe('Group type index for group-based feature flags.'),
        payloads: zod
            .record(zod.string(), zod.string())
            .optional()
            .describe('Optional payload values keyed by variant key.'),
    })
    .describe(
        "Feature-flag filters accepted by the experiment endpoints: the flag's own filters shape,\nminus the keys experiments don't apply."
    )

export type ExperimentFeatureFlagFiltersApi = zod.input<typeof ExperimentFeatureFlagFiltersApi>
export type ExperimentFeatureFlagFiltersApiOutput = zod.output<typeof ExperimentFeatureFlagFiltersApi>

export const ExperimentFeatureFlagInputApi = zod
    .object({
        filters: ExperimentFeatureFlagFiltersApi.optional().describe(
            "Flag config to apply: `multivariate.variants` (2 to 20 variants; the baseline defaults to the variant keyed 'control' when present, else the first variant), `groups` (a single group with `rollout_percentage` only; release conditions are not supported here, edit the feature flag directly), `aggregation_group_type_index`, and `payloads` (JSON-encoded strings keyed by variant key). On update, config this object omits is preserved from the linked flag's current state."
        ),
        ensure_experience_continuity: zod
            .boolean()
            .nullish()
            .describe('Whether the flag persists variant assignment across authentication steps.'),
    })
    .describe(
        "Flag config for experiment create\/update, sent through the linked feature flag's own shape.\n\nValidated both as the OpenAPI request field (via ``ExperimentWriteSerializer``) and at runtime\n(``ExperimentSerializer._normalize_feature_flag_input`` runs it against the raw feature_flag\nobject). Echoed read-only flag objects (carrying a non-null id) are handled upstream and never\nreach this validation."
    )

export type ExperimentFeatureFlagInputApi = zod.input<typeof ExperimentFeatureFlagInputApi>
export type ExperimentFeatureFlagInputApiOutput = zod.output<typeof ExperimentFeatureFlagInputApi>

export const ExperimentToSavedMetricApi = zod.object({
    id: zod.number(),
    experiment: zod.number(),
    saved_metric: zod.number(),
    metadata: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    query: zod.unknown(),
    name: zod.string(),
})

export type ExperimentToSavedMetricApi = zod.input<typeof ExperimentToSavedMetricApi>
export type ExperimentToSavedMetricApiOutput = zod.output<typeof ExperimentToSavedMetricApi>

export const ExperimentApiExposureCriteriaApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentApiExposureCriteriaApi = zod.input<typeof ExperimentApiExposureCriteriaApi>
export type ExperimentApiExposureCriteriaApiOutput = zod.output<typeof ExperimentApiExposureCriteriaApi>

export const KindApi = zod.enum(['EventsNode', 'ActionsNode'])

export type KindApi = zod.input<typeof KindApi>
export type KindApiOutput = zod.output<typeof KindApi>

export const ExperimentMetricMathTypeApi = zod.enum([
    'total',
    'sum',
    'unique_session',
    'min',
    'max',
    'avg',
    'dau',
    'unique_group',
    'hogql',
])

export type ExperimentMetricMathTypeApi = zod.input<typeof ExperimentMetricMathTypeApi>
export type ExperimentMetricMathTypeApiOutput = zod.output<typeof ExperimentMetricMathTypeApi>

export const MathGroupTypeIndexApi = zod.union([
    zod.literal(0),
    zod.literal(1),
    zod.literal(2),
    zod.literal(3),
    zod.literal(4),
])

export type MathGroupTypeIndexApi = zod.input<typeof MathGroupTypeIndexApi>
export type MathGroupTypeIndexApiOutput = zod.output<typeof MathGroupTypeIndexApi>

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

export const ExperimentApiEventSourceApi = zod.object({
    event: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
    id: zod.union([zod.number(), zod.null()]).optional().describe('Action ID. Required for ActionsNode.'),
    kind: KindApi,
    math: zod
        .union([ExperimentMetricMathTypeApi, zod.null()])
        .optional()
        .describe(
            "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
        ),
    math_group_type_index: zod
        .union([MathGroupTypeIndexApi, zod.null()])
        .optional()
        .describe("Group type index to aggregate over. Required when math is 'unique_group'."),
    math_hogql: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count\/sum."
        ),
    math_property: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."),
    properties: zod
        .union([zod.array(EventPropertyFilterApi), zod.null()])
        .optional()
        .describe('Event property filters to narrow which events are counted.'),
})

export type ExperimentApiEventSourceApi = zod.input<typeof ExperimentApiEventSourceApi>
export type ExperimentApiEventSourceApiOutput = zod.output<typeof ExperimentApiEventSourceApi>

export const experimentMetricOutlierHandlingApiLowerBoundPercentileOneMin = 0
export const experimentMetricOutlierHandlingApiLowerBoundPercentileOneMax = 1

export const experimentMetricOutlierHandlingApiUpperBoundPercentileOneMin = 0
export const experimentMetricOutlierHandlingApiUpperBoundPercentileOneMax = 1

export const ExperimentMetricOutlierHandlingApi = zod.object({
    ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
    lower_bound_percentile: zod
        .union([
            zod
                .number()
                .min(experimentMetricOutlierHandlingApiLowerBoundPercentileOneMin)
                .max(experimentMetricOutlierHandlingApiLowerBoundPercentileOneMax),
            zod.null(),
        ])
        .optional()
        .describe('Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'),
    upper_bound_percentile: zod
        .union([
            zod
                .number()
                .min(experimentMetricOutlierHandlingApiUpperBoundPercentileOneMin)
                .max(experimentMetricOutlierHandlingApiUpperBoundPercentileOneMax),
            zod.null(),
        ])
        .optional()
        .describe('Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'),
})

export type ExperimentMetricOutlierHandlingApi = zod.input<typeof ExperimentMetricOutlierHandlingApi>
export type ExperimentMetricOutlierHandlingApiOutput = zod.output<typeof ExperimentMetricOutlierHandlingApi>

export const ExperimentMetricGoalApi = zod.enum(['increase', 'decrease'])

export type ExperimentMetricGoalApi = zod.input<typeof ExperimentMetricGoalApi>
export type ExperimentMetricGoalApiOutput = zod.output<typeof ExperimentMetricGoalApi>

export const ExperimentMetricTypeApi = zod.enum(['funnel', 'mean', 'ratio', 'retention'])

export type ExperimentMetricTypeApi = zod.input<typeof ExperimentMetricTypeApi>
export type ExperimentMetricTypeApiOutput = zod.output<typeof ExperimentMetricTypeApi>

export const FunnelConversionWindowTimeUnitApi = zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month'])

export type FunnelConversionWindowTimeUnitApi = zod.input<typeof FunnelConversionWindowTimeUnitApi>
export type FunnelConversionWindowTimeUnitApiOutput = zod.output<typeof FunnelConversionWindowTimeUnitApi>

export const StartHandlingApi = zod.enum(['first_seen', 'last_seen'])

export type StartHandlingApi = zod.input<typeof StartHandlingApi>
export type StartHandlingApiOutput = zod.output<typeof StartHandlingApi>

export const experimentApiMetricApiKindDefault = `ExperimentMetric`
export const experimentApiMetricApiLowerBoundPercentileOneMin = 0
export const experimentApiMetricApiLowerBoundPercentileOneMax = 1

export const experimentApiMetricApiUpperBoundPercentileOneMin = 0
export const experimentApiMetricApiUpperBoundPercentileOneMax = 1

export const ExperimentApiMetricApi = zod.object({
    completion_event: zod
        .union([ExperimentApiEventSourceApi, zod.null()])
        .optional()
        .describe('For retention metrics: completion event.'),
    conversion_window: zod.union([zod.number(), zod.null()]).optional().describe('Conversion window duration.'),
    denominator: zod
        .union([ExperimentApiEventSourceApi, zod.null()])
        .optional()
        .describe('For ratio metrics: denominator source.'),
    denominator_outlier_handling: zod
        .union([ExperimentMetricOutlierHandlingApi, zod.null()])
        .optional()
        .describe(
            'For ratio metrics: winsorization applied to the denominator aggregate. Leave unset for a binomial-style denominator, which is never clamped.'
        ),
    goal: zod
        .union([ExperimentMetricGoalApi, zod.null()])
        .optional()
        .describe('Whether higher or lower values indicate success.'),
    ignore_zeros: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe('For mean metrics: exclude zero values when computing the winsorization percentile thresholds.'),
    kind: zod.literal('ExperimentMetric').default(experimentApiMetricApiKindDefault),
    lower_bound_percentile: zod
        .union([
            zod
                .number()
                .min(experimentApiMetricApiLowerBoundPercentileOneMin)
                .max(experimentApiMetricApiLowerBoundPercentileOneMax),
            zod.null(),
        ])
        .optional()
        .describe(
            'For mean metrics: winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). Per-user values below this percentile are clamped to it before aggregation.'
        ),
    metric_type: ExperimentMetricTypeApi,
    name: zod.union([zod.string(), zod.null()]).optional().describe('Human-readable metric name.'),
    numerator: zod
        .union([ExperimentApiEventSourceApi, zod.null()])
        .optional()
        .describe('For ratio metrics: numerator source.'),
    numerator_outlier_handling: zod
        .union([ExperimentMetricOutlierHandlingApi, zod.null()])
        .optional()
        .describe(
            'For ratio metrics: winsorization applied to the numerator aggregate, independently of the denominator and each with its own percentile thresholds.'
        ),
    retention_window_end: zod.union([zod.number(), zod.null()]).optional(),
    retention_window_start: zod.union([zod.number(), zod.null()]).optional(),
    retention_window_unit: zod.union([FunnelConversionWindowTimeUnitApi, zod.null()]).optional(),
    series: zod
        .union([zod.array(ExperimentApiEventSourceApi), zod.null()])
        .optional()
        .describe('For funnel metrics: array of EventsNode\/ActionsNode steps.'),
    source: zod.union([ExperimentApiEventSourceApi, zod.null()]).optional().describe('For mean metrics: event source.'),
    start_event: zod
        .union([ExperimentApiEventSourceApi, zod.null()])
        .optional()
        .describe('For retention metrics: start event.'),
    start_handling: zod.union([StartHandlingApi, zod.null()]).optional(),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'For mean metrics: when set, reports the percentage of users whose per-user summed\/counted value reaches or exceeds this threshold. Only meaningful for sum\/count math types.'
        ),
    upper_bound_percentile: zod
        .union([
            zod
                .number()
                .min(experimentApiMetricApiUpperBoundPercentileOneMin)
                .max(experimentApiMetricApiUpperBoundPercentileOneMax),
            zod.null(),
        ])
        .optional()
        .describe(
            'For mean metrics: winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). Per-user values above this percentile are clamped to it before aggregation.'
        ),
    uuid: zod.union([zod.string(), zod.null()]).optional().describe('Unique identifier. Auto-generated if omitted.'),
})

export type ExperimentApiMetricApi = zod.input<typeof ExperimentApiMetricApi>
export type ExperimentApiMetricApiOutput = zod.output<typeof ExperimentApiMetricApi>

export const _ExperimentApiMetricsListApi = zod
    .array(ExperimentApiMetricApi)
    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.')

export type _ExperimentApiMetricsListApi = zod.input<typeof _ExperimentApiMetricsListApi>
export type _ExperimentApiMetricsListApiOutput = zod.output<typeof _ExperimentApiMetricsListApi>

export const ExperimentApiExposureConfigApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentApiExposureConfigApi = zod.input<typeof ExperimentApiExposureConfigApi>
export type ExperimentApiExposureConfigApiOutput = zod.output<typeof ExperimentApiExposureConfigApi>

export const MultipleVariantHandlingApi = zod.enum(['exclude', 'first_seen'])

export type MultipleVariantHandlingApi = zod.input<typeof MultipleVariantHandlingApi>
export type MultipleVariantHandlingApiOutput = zod.output<typeof MultipleVariantHandlingApi>

export const Kind1Api = zod.enum(['ExperimentEventExposureConfig', 'ActionsNode'])

export type Kind1Api = zod.input<typeof Kind1Api>
export type Kind1ApiOutput = zod.output<typeof Kind1Api>

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
