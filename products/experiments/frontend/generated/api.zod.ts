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

export const experimentHoldoutsCreateBodyNameMax = 400

export const experimentHoldoutsCreateBodyDescriptionMax = 400

export const ExperimentHoldoutsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(experimentHoldoutsCreateBodyNameMax)
            .describe('Human-readable name for the holdout group.'),
        description: zod
            .string()
            .max(experimentHoldoutsCreateBodyDescriptionMax)
            .nullish()
            .describe('Optional description of what this holdout reserves and why.'),
        filters: zod
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
            .describe(
                "Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the \*\*exclusion\*\* percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person\/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout."
            ),
    })
    .describe('A holdout group — a stable slice of users excluded from experiment exposure.')

export const experimentHoldoutsUpdateBodyNameMax = 400

export const experimentHoldoutsUpdateBodyDescriptionMax = 400

export const ExperimentHoldoutsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(experimentHoldoutsUpdateBodyNameMax)
            .describe('Human-readable name for the holdout group.'),
        description: zod
            .string()
            .max(experimentHoldoutsUpdateBodyDescriptionMax)
            .nullish()
            .describe('Optional description of what this holdout reserves and why.'),
        filters: zod
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
            .describe(
                "Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the \*\*exclusion\*\* percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person\/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout."
            ),
    })
    .describe('A holdout group — a stable slice of users excluded from experiment exposure.')

export const experimentHoldoutsPartialUpdateBodyNameMax = 400

export const experimentHoldoutsPartialUpdateBodyDescriptionMax = 400

export const ExperimentHoldoutsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(experimentHoldoutsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable name for the holdout group.'),
        description: zod
            .string()
            .max(experimentHoldoutsPartialUpdateBodyDescriptionMax)
            .nullish()
            .describe('Optional description of what this holdout reserves and why.'),
        filters: zod
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
            .describe(
                "Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the \*\*exclusion\*\* percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person\/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout."
            ),
    })
    .describe('A holdout group — a stable slice of users excluded from experiment exposure.')

export const experimentSavedMetricsCreateBodyNameMax = 400

export const experimentSavedMetricsCreateBodyDescriptionMax = 400

export const ExperimentSavedMetricsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(experimentSavedMetricsCreateBodyNameMax)
            .describe('Name of the shared metric. Must be unique within the project (case-insensitive).'),
        description: zod
            .string()
            .max(experimentSavedMetricsCreateBodyDescriptionMax)
            .nullish()
            .describe('Short description of what the metric measures.'),
        query: zod
            .unknown()
            .describe(
                "ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics."
            ),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const experimentSavedMetricsUpdateBodyNameMax = 400

export const experimentSavedMetricsUpdateBodyDescriptionMax = 400

export const ExperimentSavedMetricsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(experimentSavedMetricsUpdateBodyNameMax)
            .describe('Name of the shared metric. Must be unique within the project (case-insensitive).'),
        description: zod
            .string()
            .max(experimentSavedMetricsUpdateBodyDescriptionMax)
            .nullish()
            .describe('Short description of what the metric measures.'),
        query: zod
            .unknown()
            .describe(
                "ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics."
            ),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const experimentSavedMetricsPartialUpdateBodyNameMax = 400

export const experimentSavedMetricsPartialUpdateBodyDescriptionMax = 400

export const ExperimentSavedMetricsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(experimentSavedMetricsPartialUpdateBodyNameMax)
            .optional()
            .describe('Name of the shared metric. Must be unique within the project (case-insensitive).'),
        description: zod
            .string()
            .max(experimentSavedMetricsPartialUpdateBodyDescriptionMax)
            .nullish()
            .describe('Short description of what the metric measures.'),
        query: zod
            .unknown()
            .optional()
            .describe(
                "ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics."
            ),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create a new experiment in draft status with optional metrics.
 */
export const ExperimentsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time. Feature-flag config (variants, rollout, payloads) is sent via the feature_flag object.
 */
export const ExperimentsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Archive an ended experiment.
 *
 * Hides the experiment from the default list view. The experiment can be
 * restored at any time by updating archived=false. When the linked feature
 * flag is still enabled, pass disable_feature_flag=true to also disable and
 * archive it. Returns 400 if the experiment is already archived or has not
 * ended yet.
 */
export const experimentsArchiveCreateBodyDisableFeatureFlagDefault = false

export const ExperimentsArchiveCreateBody = /* @__PURE__ */ zod.object({
    disable_feature_flag: zod
        .boolean()
        .default(experimentsArchiveCreateBodyDisableFeatureFlagDefault)
        .describe(
            'When the linked feature flag is still enabled, also disable and archive it along with the experiment. Has no effect if the flag is already disabled (it is archived either way).'
        ),
})

/**
 * Copy an experiment into another project in the same organization as a new draft.
 */
export const ExperimentsCopyToProjectCreateBody = /* @__PURE__ */ zod.object({
    target_team_id: zod.number().describe('The team ID to copy the experiment to.'),
    feature_flag_key: zod.string().optional().describe('Optional feature flag key to use in the destination team.'),
    name: zod.string().optional().describe('Optional name for the copied experiment.'),
})

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsCreateExposureCohortForExperimentCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsDuplicateCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * End a running experiment without shipping a variant.
 *
 * Sets end_date to now and marks the experiment as stopped. The feature
 * flag is NOT modified — users continue to see their assigned variants
 * and exposure events ($feature_flag_called) continue to be recorded.
 * However, only data up to end_date is included in experiment results.
 *
 * Use this when:
 *
 * - You want to freeze the results window without changing which variant
 *   users see.
 * - A variant was already shipped manually via the feature flag UI and
 *   the experiment just needs to be marked complete.
 *
 * The end_date can be adjusted after ending via PATCH if it needs to be
 * backdated (e.g. to match when the flag was actually paused).
 *
 * Other options:
 * - Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
 * - Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).
 *
 * Returns 400 if the experiment is not running.
 */
export const experimentsEndCreateBodyConclusionCommentMax = 4000

export const experimentsEndCreateBodyOpenCleanupPrDefault = false

export const ExperimentsEndCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '\* `won` - won\n\* `lost` - lost\n\* `inconclusive` - inconclusive\n\* `stopped_early` - stopped_early\n\* `invalid` - invalid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'The conclusion of the experiment.\n\n\* `won` - won\n\* `lost` - lost\n\* `inconclusive` - inconclusive\n\* `stopped_early` - stopped_early\n\* `invalid` - invalid'
        ),
    conclusion_comment: zod
        .string()
        .max(experimentsEndCreateBodyConclusionCommentMax)
        .nullish()
        .describe('Optional comment about the experiment conclusion.'),
    open_cleanup_pr: zod
        .boolean()
        .default(experimentsEndCreateBodyOpenCleanupPrDefault)
        .describe(
            "When true, open a draft pull request that removes the experiment's feature-flag code from the linked repository. Requires the requesting user to have access to PostHog Code (403 otherwise). Only acts for allowlisted teams; ignored otherwise."
        ),
})

/**
 * Trigger a batch recalculation of all metrics for this experiment.
 *
 * Returns 201 with the new pending recalculation, or 200 with the active one if a recalculation is
 * already pending or in progress for this experiment. The response payload intentionally does not
 * include the `results` array — at POST time the workflow has just been queued and no per-metric
 * results exist yet. Clients should poll `GET metrics_recalculation/{id}/` for results as the workflow
 * progresses.
 */
export const experimentsMetricsRecalculationCreateBodyTriggerDefault = `manual`

export const ExperimentsMetricsRecalculationCreateBody = /* @__PURE__ */ zod
    .object({
        trigger: zod
            .enum([
                'manual',
                'cold_run',
                'stale_refresh',
                'auto_refresh',
                'config_change',
                'experiment_launch',
                'experiment_stop',
                'experiment_update',
            ])
            .describe(
                '\* `manual` - Manual\n\* `cold_run` - Cold Run\n\* `stale_refresh` - Stale Refresh\n\* `auto_refresh` - Auto Refresh\n\* `config_change` - Config Change\n\* `experiment_launch` - Experiment Launch\n\* `experiment_stop` - Experiment Stop\n\* `experiment_update` - Experiment Update'
            )
            .default(experimentsMetricsRecalculationCreateBodyTriggerDefault)
            .describe(
                'What triggered this recalculation (manual is the default for user-initiated runs)\n\n\* `manual` - Manual\n\* `cold_run` - Cold Run\n\* `stale_refresh` - Stale Refresh\n\* `auto_refresh` - Auto Refresh\n\* `config_change` - Config Change\n\* `experiment_launch` - Experiment Launch\n\* `experiment_stop` - Experiment Stop\n\* `experiment_update` - Experiment Update'
            ),
    })
    .describe('Request body for triggering a metrics recalculation.')

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsRecalculateTimeseriesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Ship a variant and (optionally) end the experiment.
 *
 * Updates the feature flag so the selected variant gets 100% of the variant
 * distribution. By default, existing release conditions on the flag are preserved
 * untouched — the variant is served only to users who already match them. Pass
 * ``release_to_everyone: true`` to also prepend a catch-all release condition
 * that rolls the variant out to 100% of users (overrides any existing release
 * conditions on the flag).
 *
 * Can be called on both running and stopped experiments. If the experiment is
 * still running, it will also be ended (end_date set and status marked as stopped).
 * If the experiment has already ended, only the flag is rewritten - this supports
 * the "end first, ship later" workflow.
 *
 * If an approval policy requires review before changes on the flag take effect,
 * the API returns 409 with a change_request_id. The experiment is NOT ended until
 * the change request is approved and the user retries.
 *
 * Returns 400 if the experiment is in draft state, the variant_key is not found
 * on the flag, or the experiment has no linked feature flag.
 */
export const experimentsShipVariantCreateBodyConclusionCommentMax = 4000

export const experimentsShipVariantCreateBodyOpenCleanupPrDefault = false
export const experimentsShipVariantCreateBodyReleaseToEveryoneDefault = false

export const ExperimentsShipVariantCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '\* `won` - won\n\* `lost` - lost\n\* `inconclusive` - inconclusive\n\* `stopped_early` - stopped_early\n\* `invalid` - invalid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'The conclusion of the experiment.\n\n\* `won` - won\n\* `lost` - lost\n\* `inconclusive` - inconclusive\n\* `stopped_early` - stopped_early\n\* `invalid` - invalid'
        ),
    conclusion_comment: zod
        .string()
        .max(experimentsShipVariantCreateBodyConclusionCommentMax)
        .nullish()
        .describe('Optional comment about the experiment conclusion.'),
    open_cleanup_pr: zod
        .boolean()
        .default(experimentsShipVariantCreateBodyOpenCleanupPrDefault)
        .describe(
            "When true, open a draft pull request that removes the experiment's feature-flag code from the linked repository. Requires the requesting user to have access to PostHog Code (403 otherwise). Only acts for allowlisted teams; ignored otherwise."
        ),
    variant_key: zod.string().describe('The key of the variant to ship.'),
    release_to_everyone: zod
        .boolean()
        .default(experimentsShipVariantCreateBodyReleaseToEveryoneDefault)
        .describe(
            'If true, prepend a release condition to the feature flag that rolls the variant out to 100% of users, overriding any existing release conditions on the flag. If false (default), only update the variant distribution — existing release conditions are preserved and the variant is served only to users who already match them.'
        ),
})

/**
 * Estimate the recommended sample size and running time for an experiment.
 *
 * Pure statistical calculation — does not read or write any experiment. Pass the metric type, a
 * minimum detectable effect, and either a baseline value or raw baseline statistics. When
 * `exposure_rate_per_day` is provided, the response also includes the estimated running time in days.
 */
export const experimentsCalculateRunningTimeCreateBodyMinimumDetectableEffectMin = 0

export const experimentsCalculateRunningTimeCreateBodyNumberOfVariantsDefault = 2
export const experimentsCalculateRunningTimeCreateBodyNumberOfVariantsMin = 2

export const experimentsCalculateRunningTimeCreateBodyExposureRatePerDayMin = 0

export const experimentsCalculateRunningTimeCreateBodyBaselineStatsOneNumberOfSamplesMin = 0

export const experimentsCalculateRunningTimeCreateBodyBaselineStatsOneSumSquaresDefault = 0

export const ExperimentsCalculateRunningTimeCreateBody = /* @__PURE__ */ zod
    .object({
        metric_type: zod
            .enum(['funnel', 'mean_count', 'mean_sum_or_avg', 'ratio', 'retention'])
            .describe(
                '\* `funnel` - funnel\n\* `mean_count` - mean_count\n\* `mean_sum_or_avg` - mean_sum_or_avg\n\* `ratio` - ratio\n\* `retention` - retention'
            )
            .describe(
                "Metric type to size for. 'funnel' for conversion rates, 'mean_count' for event counts per user, 'mean_sum_or_avg' for summed property values per user, 'ratio' and 'retention' for ratio-style metrics (both require baseline_stats or an explicit variance).\n\n\* `funnel` - funnel\n\* `mean_count` - mean_count\n\* `mean_sum_or_avg` - mean_sum_or_avg\n\* `ratio` - ratio\n\* `retention` - retention"
            ),
        minimum_detectable_effect: zod
            .number()
            .min(experimentsCalculateRunningTimeCreateBodyMinimumDetectableEffectMin)
            .describe('Smallest relative change to detect, as a percentage (e.g. 5 means a 5% lift). Must be > 0.'),
        number_of_variants: zod
            .number()
            .min(experimentsCalculateRunningTimeCreateBodyNumberOfVariantsMin)
            .default(experimentsCalculateRunningTimeCreateBodyNumberOfVariantsDefault)
            .describe('Total number of variants including control (default 2).'),
        exposure_rate_per_day: zod
            .number()
            .min(experimentsCalculateRunningTimeCreateBodyExposureRatePerDayMin)
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
            .union([
                zod
                    .object({
                        number_of_samples: zod
                            .number()
                            .min(experimentsCalculateRunningTimeCreateBodyBaselineStatsOneNumberOfSamplesMin)
                            .describe('Number of control-group samples (users\/units) observed.'),
                        sum: zod
                            .number()
                            .describe(
                                'Sum of the metric values across the control group (for funnels, the numerator\/conversions).'
                            ),
                        sum_squares: zod
                            .number()
                            .default(experimentsCalculateRunningTimeCreateBodyBaselineStatsOneSumSquaresDefault)
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
                            .describe(
                                'Sum of numerator×denominator products, used for the delta-method covariance term.'
                            ),
                        step_counts: zod
                            .array(zod.number())
                            .optional()
                            .describe('Per-step counts for funnel metrics; the last entry is the final-step count.'),
                    })
                    .describe(
                        'Raw control-group statistics the calculator uses to derive a baseline value and variance.\n\nSupply this when you want the server to compute the baseline value and (for ratio\/retention)\nthe delta-method variance, instead of passing `baseline_value`\/`variance` directly.'
                    ),
                zod.null(),
            ])
            .optional()
            .describe('Raw control-group statistics. When provided, the server derives baseline_value and variance.'),
    })
    .describe('Inputs for estimating the recommended sample size and running time of an experiment.')

/**
 * Create an experiment that compares N versions of an LLM prompt using a metric template.
 *
 * The user picks 2+ versions of an existing LLMPrompt and 1+ metric templates
 * (cost / latency / eval_pass_rate). The endpoint builds the matching variants
 * (control + test-N, each named after its prompt version) and attaches one
 * metric per selected template, each scoped to the prompt's $ai_prompt_name.
 * Resulting experiment is in draft state.
 */

export const experimentsCreateFromPromptCreateBodyVersionsMin = 2
export const experimentsCreateFromPromptCreateBodyVersionsMax = 10

export const experimentsCreateFromPromptCreateBodyTemplatesMax = 3

export const ExperimentsCreateFromPromptCreateBody = /* @__PURE__ */ zod.object({
    prompt_name: zod
        .string()
        .describe('The name of the LLM prompt to experiment on. Must already exist for this team.'),
    versions: zod
        .array(zod.number().min(1))
        .min(experimentsCreateFromPromptCreateBodyVersionsMin)
        .max(experimentsCreateFromPromptCreateBodyVersionsMax)
        .describe(
            'Ordered list of prompt version numbers to assign to experiment variants. The first entry is the control variant. Must contain between 2 and 10 distinct versions.'
        ),
    templates: zod
        .array(
            zod
                .enum(['cost', 'latency', 'eval_pass_rate'])
                .describe('\* `cost` - cost\n\* `latency` - latency\n\* `eval_pass_rate` - eval_pass_rate')
        )
        .min(1)
        .max(experimentsCreateFromPromptCreateBodyTemplatesMax)
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
