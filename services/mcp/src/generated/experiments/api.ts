/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 28 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ExperimentHoldoutsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentHoldoutsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ExperimentHoldoutsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
                                        .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
                                        .describe(
                                            '* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after'
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
            .describe(
                "Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the **exclusion** percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout."
            ),
    })
    .describe('A holdout group — a stable slice of users excluded from experiment exposure.')

export const ExperimentHoldoutsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment holdout.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentHoldoutsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment holdout.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
                                        .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
                                        .describe(
                                            '* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after'
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
            .describe(
                "Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the **exclusion** percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout."
            ),
    })
    .describe('A holdout group — a stable slice of users excluded from experiment exposure.')

export const ExperimentHoldoutsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment holdout.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentSavedMetricsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentSavedMetricsListQueryParams = /* @__PURE__ */ zod.object({
    event: zod
        .string()
        .optional()
        .describe(
            "Filter to shared metrics whose query references this event name. Matches events used directly in metric queries as well as events behind any actions those metrics reference. Use this for reuse discovery (find a metric by what it measures); distinct from 'search', which matches the metric's own name/description/tags."
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const ExperimentSavedMetricsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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

export const ExperimentSavedMetricsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment saved metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentSavedMetricsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment saved metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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

export const ExperimentSavedMetricsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment saved metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List experiments for the current project. Supports filtering by status and archival state.
 */
export const ExperimentsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsListQueryParams = /* @__PURE__ */ zod.object({
    archived: zod.boolean().optional().describe('Filter by archived state. Defaults to non-archived experiments only.'),
    created_by_id: zod
        .string()
        .optional()
        .describe(
            'Filter to experiments created by the given user(s). Accepts a single user ID, or a JSON-encoded / comma-separated list of user IDs to match any of them.'
        ),
    event: zod
        .string()
        .optional()
        .describe(
            'Filter to experiments whose metrics reference this event name. Matches events used directly in metric queries as well as events behind any actions those metrics reference.'
        ),
    feature_flag_id: zod.number().optional().describe('Filter to experiments linked to the given feature flag ID.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order: zod
        .string()
        .optional()
        .describe(
            "Field to order by. Prefix with '-' for descending. Allowlisted fields include name, created_at, updated_at, start_date, end_date, duration, and status."
        ),
    prompt_name: zod
        .string()
        .optional()
        .describe(
            'Filter to experiments created from an LLM prompt with this name. Matches experiments whose parameters.prompt_metadata.name equals the given value.'
        ),
    search: zod.string().optional().describe('Free-text search applied to the experiment name (case-insensitive).'),
    status: zod
        .enum(['all', 'complete', 'draft', 'paused', 'running', 'stopped'])
        .optional()
        .describe(
            'Filter by experiment status. "running" and "paused" are mutually exclusive: "running" returns launched experiments with an active feature flag, "paused" returns launched experiments whose feature flag is deactivated. "complete" is an alias for "stopped". "all" disables status filtering.'
        ),
})

/**
 * Create a new experiment in draft status with optional metrics.
 */
export const ExperimentsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsCreateBodyNameMax = 400

export const experimentsCreateBodyDescriptionMax = 3000

export const experimentsCreateBodyArchivedDefault = false
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneOperatorDefault = `exact`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneTypeDefault = `event`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwoTypeDefault = `person`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemThreeTypeDefault = `person_metadata`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFourTypeDefault = `element`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFiveTypeDefault = `event_metadata`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSixTypeDefault = `session`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenKeyDefault = `id`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenOperatorDefault = `in`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenTypeDefault = `cohort`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemEightTypeDefault = `recording`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemNineTypeDefault = `log_entry`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnezeroTypeDefault = `group`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneoneTypeDefault = `feature`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoTypeDefault = `flag`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnethreeTypeDefault = `hogql`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefourTypeDefault = `empty`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefiveTypeDefault = `data_warehouse`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesixTypeDefault = `data_warehouse_person_property`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesevenTypeDefault = `error_tracking_issue`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwozeroTypeDefault = `revenue_analytics`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwooneTypeDefault = `workflow_variable`
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsCreateBodyMetricsOneItemLowerBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsOneItemLowerBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemUpperBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsOneItemUpperBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsCreateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMin = 0
export const experimentsCreateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMax = 1

export const experimentsCreateBodyAllowUnknownEventsDefault = false
export const experimentsCreateBodyConclusionCommentMax = 4000

export const experimentsCreateBodyUpdateFeatureFlagParamsDefault = false

export const ExperimentsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsCreateBodyNameMax).describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsCreateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        feature_flag_key: zod
            .string()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .union([
                zod.object({
                    feature_flag_variants: zod
                        .union([
                            zod.array(
                                zod.object({
                                    key: zod
                                        .string()
                                        .describe(
                                            "Variant key. Exactly one variant in feature_flag_variants must use key 'control' (lowercase, exactly) — that is the baseline used for analysis and the special key the experiment runtime expects. Other variants use keys like 'test', 'variant_a', 'variant_b'. Map natural-language names ('original', 'A', 'baseline') to 'control'."
                                        ),
                                    name: zod
                                        .union([zod.string(), zod.null()])
                                        .optional()
                                        .describe('Human-readable variant name.'),
                                    rollout_percentage: zod.union([zod.number(), zod.null()]).optional(),
                                    split_percent: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                        ),
                                })
                            ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            "Experiment variants. If specified, must include a variant with key 'control' (lowercase). Defaults to a 50/50 control/test split when omitted. Minimum 2, maximum 20."
                        ),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                        ),
                    rollout_percentage: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                        ),
                    variant_notes: zod
                        .union([zod.record(zod.string(), zod.string()), zod.null()])
                        .optional()
                        .describe(
                            'Free-text notes per variant, keyed by variant key. Use to document what each variant does or its reroute URL.'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment parameters JSON. Supported keys include `custom_exposure_filter` and `variant_notes` (free-text notes per variant, keyed by variant key). Flag config keys (`feature_flag_variants`, `rollout_percentage`) are a deprecated input surface kept for compatibility — the linked feature flag is the source of truth, and reads project its current config into this field. Excluded variants live on the top-level `excluded_variants` field, not here.'
            ),
        running_time_calculation: zod
            .union([
                zod.object({
                    exposure_estimate_config: zod
                        .union([
                            zod.object({
                                conversionRateInputType: zod
                                    .enum(['manual', 'automatic'])
                                    .describe(
                                        "'manual' when the baseline value and exposure rate were entered by hand, 'automatic' when derived from live experiment data."
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
                                    .describe(
                                        'Manually entered estimate of users exposed to the experiment per day. Only used in manual mode.'
                                    ),
                                manualMetricType: zod
                                    .union([zod.enum(['funnel', 'mean_count', 'mean_sum_or_avg']), zod.null()])
                                    .optional()
                                    .describe(
                                        'Metric type the manual baseline value refers to. Only used in manual mode.'
                                    ),
                            }),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'How the exposure estimate is configured: manual user-entered values or automatic from live experiment data.'
                        ),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes.'
                        ),
                    recommended_running_time: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe('Estimated number of days needed to reach the recommended sample size.'),
                    recommended_sample_size: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe('Recommended number of exposed users needed for statistical significance.'),
                }),
                zod.null(),
            ])
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
        secondary_metrics: zod.unknown().optional(),
        saved_metrics_ids: zod
            .array(zod.unknown())
            .nullish()
            .describe(
                "IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary)."
            ),
        filters: zod.unknown().optional(),
        archived: zod
            .boolean()
            .default(experimentsCreateBodyArchivedDefault)
            .describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        type: zod
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.null()])
            .optional()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .union([
                zod.object({
                    exposure_config: zod
                        .union([
                            zod.object({
                                event: zod
                                    .union([zod.string(), zod.null()])
                                    .optional()
                                    .describe(
                                        "Custom exposure event name. Required when kind is 'ExperimentEventExposureConfig'."
                                    ),
                                id: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe("Action ID. Required when kind is 'ActionsNode'."),
                                kind: zod
                                    .union([zod.enum(['ExperimentEventExposureConfig', 'ActionsNode']), zod.null()])
                                    .optional()
                                    .describe(
                                        "Defaults to 'ExperimentEventExposureConfig' when omitted. Pass 'ActionsNode' for an action-based exposure."
                                    ),
                                properties: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .union([
                                                        zod.enum([
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
                                                        ]),
                                                        zod.null(),
                                                    ])
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneOperatorDefault
                                                    ),
                                                type: zod
                                                    .literal('event')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneTypeDefault
                                                    )
                                                    .describe('Event properties'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('person')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwoTypeDefault
                                                    )
                                                    .describe('Person properties'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('person_metadata')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemThreeTypeDefault
                                                    )
                                                    .describe(
                                                        'Top-level columns on the persons table (e.g. created_at), not properties JSON'
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('element')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFourTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('event_metadata')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFiveTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('session')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSixTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                cohort_name: zod.union([zod.string(), zod.null()]).optional(),
                                                key: zod
                                                    .literal('id')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenKeyDefault
                                                    ),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .union([
                                                        zod.enum([
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
                                                        ]),
                                                        zod.null(),
                                                    ])
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenOperatorDefault
                                                    ),
                                                type: zod
                                                    .literal('cohort')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenTypeDefault
                                                    ),
                                                value: zod.number(),
                                            }),
                                            zod.object({
                                                key: zod.union([
                                                    zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                                    zod.string(),
                                                ]),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('recording')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemEightTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('log_entry')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemNineTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                group_key_names: zod
                                                    .union([zod.record(zod.string(), zod.string()), zod.null()])
                                                    .optional(),
                                                group_type_index: zod.union([zod.number(), zod.null()]).optional(),
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('group')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnezeroTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('feature')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneoneTypeDefault
                                                    )
                                                    .describe('Event property with "$feature/" prepended'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string().describe('The key should be the flag ID'),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .literal('flag_evaluates_to')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoOperatorDefault
                                                    )
                                                    .describe(
                                                        'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                    ),
                                                type: zod
                                                    .literal('flag')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoTypeDefault
                                                    )
                                                    .describe('Feature flag dependency'),
                                                value: zod
                                                    .union([zod.boolean(), zod.string()])
                                                    .describe('The value can be true, false, or a variant name'),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                type: zod
                                                    .literal('hogql')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnethreeTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                type: zod
                                                    .literal('empty')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefourTypeDefault
                                                    ),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('data_warehouse')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefiveTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('data_warehouse_person_property')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesixTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('error_tracking_issue')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesevenTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('revenue_analytics')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwozeroTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('workflow_variable')
                                                    .default(
                                                        experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwooneTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                        ])
                                    )
                                    .describe(
                                        'Property filters (event, person, and other supported types). Pass an empty array if no filters needed.'
                                    ),
                            }),
                            zod.null(),
                        ])
                        .optional(),
                    filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                    multiple_variant_handling: zod
                        .union([zod.enum(['exclude', 'first_seen']), zod.null()])
                        .optional()
                        .describe(
                            "How to handle entities exposed to multiple variants. 'exclude' (default) drops them from the analysis; 'first_seen' assigns them to the variant from their earliest exposure."
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: denominator source.'),
                            denominator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsCreateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsCreateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsCreateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsCreateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the denominator aggregate. Leave unset for a binomial-style denominator, which is never clamped.'
                                ),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .optional()
                                .describe('Whether higher or lower values indicate success.'),
                            ignore_zeros: zod
                                .union([zod.boolean(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: exclude zero values when computing the winsorization percentile thresholds.'
                                ),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsCreateBodyMetricsOneItemKindDefault),
                            lower_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(experimentsCreateBodyMetricsOneItemLowerBoundPercentileOneMin)
                                        .max(experimentsCreateBodyMetricsOneItemLowerBoundPercentileOneMax),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). Per-user values below this percentile are clamped to it before aggregation.'
                                ),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: numerator source.'),
                            numerator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsCreateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsCreateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsCreateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsCreateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the numerator aggregate, independently of the denominator and each with its own percentile thresholds.'
                                ),
                            retention_window_end: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_start: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .optional(),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            math: zod
                                                .union([
                                                    zod.enum([
                                                        'total',
                                                        'sum',
                                                        'unique_session',
                                                        'min',
                                                        'max',
                                                        'avg',
                                                        'dau',
                                                        'unique_group',
                                                        'hogql',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                                ),
                                            math_group_type_index: zod
                                                .union([
                                                    zod.union([
                                                        zod.literal(0),
                                                        zod.literal(1),
                                                        zod.literal(2),
                                                        zod.literal(3),
                                                        zod.literal(4),
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Group type index to aggregate over. Required when math is 'unique_group'."
                                                ),
                                            math_hogql: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                                ),
                                            math_property: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                                ),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: start event.'),
                            start_handling: zod.union([zod.enum(['first_seen', 'last_seen']), zod.null()]).optional(),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: when set, reports the percentage of users whose per-user summed/counted value reaches or exceeds this threshold. Only meaningful for sum/count math types.'
                                ),
                            upper_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(experimentsCreateBodyMetricsOneItemUpperBoundPercentileOneMin)
                                        .max(experimentsCreateBodyMetricsOneItemUpperBoundPercentileOneMax),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). Per-user values above this percentile are clamped to it before aggregation.'
                                ),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the read-data-schema tool with query kind 'events' to find available events in the project."
            ),
        metrics_secondary: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: denominator source.'),
                            denominator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the denominator aggregate. Leave unset for a binomial-style denominator, which is never clamped.'
                                ),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .optional()
                                .describe('Whether higher or lower values indicate success.'),
                            ignore_zeros: zod
                                .union([zod.boolean(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: exclude zero values when computing the winsorization percentile thresholds.'
                                ),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsCreateBodyMetricsSecondaryOneItemKindDefault),
                            lower_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(experimentsCreateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMin)
                                        .max(experimentsCreateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMax),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). Per-user values below this percentile are clamped to it before aggregation.'
                                ),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: numerator source.'),
                            numerator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the numerator aggregate, independently of the denominator and each with its own percentile thresholds.'
                                ),
                            retention_window_end: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_start: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .optional(),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            math: zod
                                                .union([
                                                    zod.enum([
                                                        'total',
                                                        'sum',
                                                        'unique_session',
                                                        'min',
                                                        'max',
                                                        'avg',
                                                        'dau',
                                                        'unique_group',
                                                        'hogql',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                                ),
                                            math_group_type_index: zod
                                                .union([
                                                    zod.union([
                                                        zod.literal(0),
                                                        zod.literal(1),
                                                        zod.literal(2),
                                                        zod.literal(3),
                                                        zod.literal(4),
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Group type index to aggregate over. Required when math is 'unique_group'."
                                                ),
                                            math_hogql: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                                ),
                                            math_property: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                                ),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: start event.'),
                            start_handling: zod.union([zod.enum(['first_seen', 'last_seen']), zod.null()]).optional(),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: when set, reports the percentage of users whose per-user summed/counted value reaches or exceeds this threshold. Only meaningful for sum/count math types.'
                                ),
                            upper_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(experimentsCreateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMin)
                                        .max(experimentsCreateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMax),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). Per-user values above this percentile are clamped to it before aggregation.'
                                ),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().optional(),
        scheduling_config: zod.unknown().optional(),
        allow_unknown_events: zod
            .boolean()
            .default(experimentsCreateBodyAllowUnknownEventsDefault)
            .describe(
                "Suppresses the validation that rejects metrics referencing events not yet ingested by this project. REQUIRES explicit user confirmation before being set to true — never flip this silently to retry a failed call. The default validation catches typo'd event names and missing instrumentation. Set this to true only when the user has confirmed the event is intentional (e.g. they are about to instrument it)."
            ),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod
            .string()
            .max(experimentsCreateBodyConclusionCommentMax)
            .nullish()
            .describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().optional(),
        secondary_metrics_ordered_uuids: zod.unknown().optional(),
        only_count_matured_users: zod.boolean().optional(),
        update_feature_flag_params: zod
            .boolean()
            .default(experimentsCreateBodyUpdateFeatureFlagParamsDefault)
            .describe(
                'When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts.'
            ),
    })
    .describe(
        'Full experiment representation for the detail, create, and update endpoints.\n\nExtends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric\ndefinitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side\nfields, and refreshes stale action names while serializing. The list endpoint uses the\nleaner ``ExperimentBasicSerializer`` instead.'
    )

/**
 * Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.
 */
export const ExperimentsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time.
 */
export const ExperimentsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsPartialUpdateBodyNameMax = 400

export const experimentsPartialUpdateBodyDescriptionMax = 3000

export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneOperatorDefault = `exact`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneTypeDefault = `event`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwoTypeDefault = `person`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemThreeTypeDefault = `person_metadata`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFourTypeDefault = `element`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFiveTypeDefault = `event_metadata`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSixTypeDefault = `session`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenKeyDefault = `id`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenOperatorDefault = `in`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenTypeDefault = `cohort`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemEightTypeDefault = `recording`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemNineTypeDefault = `log_entry`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnezeroTypeDefault = `group`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneoneTypeDefault = `feature`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoTypeDefault = `flag`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnethreeTypeDefault = `hogql`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefourTypeDefault = `empty`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefiveTypeDefault = `data_warehouse`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesixTypeDefault = `data_warehouse_person_property`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesevenTypeDefault = `error_tracking_issue`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwozeroTypeDefault = `revenue_analytics`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwooneTypeDefault = `workflow_variable`
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsPartialUpdateBodyMetricsOneItemLowerBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsOneItemLowerBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemUpperBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsOneItemUpperBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMin = 0
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMax = 1

export const experimentsPartialUpdateBodyConclusionCommentMax = 4000

export const ExperimentsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsPartialUpdateBodyNameMax).optional().describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsPartialUpdateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        feature_flag_key: zod
            .string()
            .optional()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .union([
                zod.object({
                    feature_flag_variants: zod
                        .union([
                            zod.array(
                                zod.object({
                                    key: zod
                                        .string()
                                        .describe(
                                            "Variant key. Exactly one variant in feature_flag_variants must use key 'control' (lowercase, exactly) — that is the baseline used for analysis and the special key the experiment runtime expects. Other variants use keys like 'test', 'variant_a', 'variant_b'. Map natural-language names ('original', 'A', 'baseline') to 'control'."
                                        ),
                                    name: zod
                                        .union([zod.string(), zod.null()])
                                        .optional()
                                        .describe('Human-readable variant name.'),
                                    rollout_percentage: zod.union([zod.number(), zod.null()]).optional(),
                                    split_percent: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                        ),
                                })
                            ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            "Experiment variants. If specified, must include a variant with key 'control' (lowercase). Defaults to a 50/50 control/test split when omitted. Minimum 2, maximum 20."
                        ),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                        ),
                    rollout_percentage: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                        ),
                    variant_notes: zod
                        .union([zod.record(zod.string(), zod.string()), zod.null()])
                        .optional()
                        .describe(
                            'Free-text notes per variant, keyed by variant key. Use to document what each variant does or its reroute URL.'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment parameters JSON. Supported keys include `custom_exposure_filter` and `variant_notes` (free-text notes per variant, keyed by variant key). Flag config keys (`feature_flag_variants`, `rollout_percentage`) are a deprecated input surface kept for compatibility — the linked feature flag is the source of truth, and reads project its current config into this field. Excluded variants live on the top-level `excluded_variants` field, not here.'
            ),
        running_time_calculation: zod
            .union([
                zod.object({
                    exposure_estimate_config: zod
                        .union([
                            zod.object({
                                conversionRateInputType: zod
                                    .enum(['manual', 'automatic'])
                                    .describe(
                                        "'manual' when the baseline value and exposure rate were entered by hand, 'automatic' when derived from live experiment data."
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
                                    .describe(
                                        'Manually entered estimate of users exposed to the experiment per day. Only used in manual mode.'
                                    ),
                                manualMetricType: zod
                                    .union([zod.enum(['funnel', 'mean_count', 'mean_sum_or_avg']), zod.null()])
                                    .optional()
                                    .describe(
                                        'Metric type the manual baseline value refers to. Only used in manual mode.'
                                    ),
                            }),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'How the exposure estimate is configured: manual user-entered values or automatic from live experiment data.'
                        ),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes.'
                        ),
                    recommended_running_time: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe('Estimated number of days needed to reach the recommended sample size.'),
                    recommended_sample_size: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe('Recommended number of exposed users needed for statistical significance.'),
                }),
                zod.null(),
            ])
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
        secondary_metrics: zod.unknown().optional(),
        saved_metrics_ids: zod
            .array(zod.unknown())
            .nullish()
            .describe(
                "IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary)."
            ),
        filters: zod.unknown().optional(),
        archived: zod.boolean().optional().describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        type: zod
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.null()])
            .optional()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .union([
                zod.object({
                    exposure_config: zod
                        .union([
                            zod.object({
                                event: zod
                                    .union([zod.string(), zod.null()])
                                    .optional()
                                    .describe(
                                        "Custom exposure event name. Required when kind is 'ExperimentEventExposureConfig'."
                                    ),
                                id: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe("Action ID. Required when kind is 'ActionsNode'."),
                                kind: zod
                                    .union([zod.enum(['ExperimentEventExposureConfig', 'ActionsNode']), zod.null()])
                                    .optional()
                                    .describe(
                                        "Defaults to 'ExperimentEventExposureConfig' when omitted. Pass 'ActionsNode' for an action-based exposure."
                                    ),
                                properties: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .union([
                                                        zod.enum([
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
                                                        ]),
                                                        zod.null(),
                                                    ])
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneOperatorDefault
                                                    ),
                                                type: zod
                                                    .literal('event')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneTypeDefault
                                                    )
                                                    .describe('Event properties'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('person')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwoTypeDefault
                                                    )
                                                    .describe('Person properties'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('person_metadata')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemThreeTypeDefault
                                                    )
                                                    .describe(
                                                        'Top-level columns on the persons table (e.g. created_at), not properties JSON'
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('element')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFourTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('event_metadata')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFiveTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('session')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSixTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                cohort_name: zod.union([zod.string(), zod.null()]).optional(),
                                                key: zod
                                                    .literal('id')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenKeyDefault
                                                    ),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .union([
                                                        zod.enum([
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
                                                        ]),
                                                        zod.null(),
                                                    ])
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenOperatorDefault
                                                    ),
                                                type: zod
                                                    .literal('cohort')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenTypeDefault
                                                    ),
                                                value: zod.number(),
                                            }),
                                            zod.object({
                                                key: zod.union([
                                                    zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                                    zod.string(),
                                                ]),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('recording')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemEightTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('log_entry')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemNineTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                group_key_names: zod
                                                    .union([zod.record(zod.string(), zod.string()), zod.null()])
                                                    .optional(),
                                                group_type_index: zod.union([zod.number(), zod.null()]).optional(),
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('group')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnezeroTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('feature')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneoneTypeDefault
                                                    )
                                                    .describe('Event property with "$feature/" prepended'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string().describe('The key should be the flag ID'),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .literal('flag_evaluates_to')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoOperatorDefault
                                                    )
                                                    .describe(
                                                        'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                    ),
                                                type: zod
                                                    .literal('flag')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoTypeDefault
                                                    )
                                                    .describe('Feature flag dependency'),
                                                value: zod
                                                    .union([zod.boolean(), zod.string()])
                                                    .describe('The value can be true, false, or a variant name'),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                type: zod
                                                    .literal('hogql')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnethreeTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                type: zod
                                                    .literal('empty')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefourTypeDefault
                                                    ),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('data_warehouse')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefiveTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('data_warehouse_person_property')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesixTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('error_tracking_issue')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesevenTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('revenue_analytics')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwozeroTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('workflow_variable')
                                                    .default(
                                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwooneTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                        ])
                                    )
                                    .describe(
                                        'Property filters (event, person, and other supported types). Pass an empty array if no filters needed.'
                                    ),
                            }),
                            zod.null(),
                        ])
                        .optional(),
                    filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                    multiple_variant_handling: zod
                        .union([zod.enum(['exclude', 'first_seen']), zod.null()])
                        .optional()
                        .describe(
                            "How to handle entities exposed to multiple variants. 'exclude' (default) drops them from the analysis; 'first_seen' assigns them to the variant from their earliest exposure."
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: denominator source.'),
                            denominator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsPartialUpdateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsPartialUpdateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsPartialUpdateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsPartialUpdateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the denominator aggregate. Leave unset for a binomial-style denominator, which is never clamped.'
                                ),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .optional()
                                .describe('Whether higher or lower values indicate success.'),
                            ignore_zeros: zod
                                .union([zod.boolean(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: exclude zero values when computing the winsorization percentile thresholds.'
                                ),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsPartialUpdateBodyMetricsOneItemKindDefault),
                            lower_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(experimentsPartialUpdateBodyMetricsOneItemLowerBoundPercentileOneMin)
                                        .max(experimentsPartialUpdateBodyMetricsOneItemLowerBoundPercentileOneMax),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). Per-user values below this percentile are clamped to it before aggregation.'
                                ),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: numerator source.'),
                            numerator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsPartialUpdateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsPartialUpdateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsPartialUpdateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsPartialUpdateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the numerator aggregate, independently of the denominator and each with its own percentile thresholds.'
                                ),
                            retention_window_end: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_start: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .optional(),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            math: zod
                                                .union([
                                                    zod.enum([
                                                        'total',
                                                        'sum',
                                                        'unique_session',
                                                        'min',
                                                        'max',
                                                        'avg',
                                                        'dau',
                                                        'unique_group',
                                                        'hogql',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                                ),
                                            math_group_type_index: zod
                                                .union([
                                                    zod.union([
                                                        zod.literal(0),
                                                        zod.literal(1),
                                                        zod.literal(2),
                                                        zod.literal(3),
                                                        zod.literal(4),
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Group type index to aggregate over. Required when math is 'unique_group'."
                                                ),
                                            math_hogql: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                                ),
                                            math_property: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                                ),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: start event.'),
                            start_handling: zod.union([zod.enum(['first_seen', 'last_seen']), zod.null()]).optional(),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: when set, reports the percentage of users whose per-user summed/counted value reaches or exceeds this threshold. Only meaningful for sum/count math types.'
                                ),
                            upper_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(experimentsPartialUpdateBodyMetricsOneItemUpperBoundPercentileOneMin)
                                        .max(experimentsPartialUpdateBodyMetricsOneItemUpperBoundPercentileOneMax),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). Per-user values above this percentile are clamped to it before aggregation.'
                                ),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the read-data-schema tool with query kind 'events' to find available events in the project."
            ),
        metrics_secondary: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: denominator source.'),
                            denominator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the denominator aggregate. Leave unset for a binomial-style denominator, which is never clamped.'
                                ),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .optional()
                                .describe('Whether higher or lower values indicate success.'),
                            ignore_zeros: zod
                                .union([zod.boolean(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: exclude zero values when computing the winsorization percentile thresholds.'
                                ),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemKindDefault),
                            lower_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(
                                            experimentsPartialUpdateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMin
                                        )
                                        .max(
                                            experimentsPartialUpdateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMax
                                        ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). Per-user values below this percentile are clamped to it before aggregation.'
                                ),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: numerator source.'),
                            numerator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the numerator aggregate, independently of the denominator and each with its own percentile thresholds.'
                                ),
                            retention_window_end: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_start: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .optional(),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            math: zod
                                                .union([
                                                    zod.enum([
                                                        'total',
                                                        'sum',
                                                        'unique_session',
                                                        'min',
                                                        'max',
                                                        'avg',
                                                        'dau',
                                                        'unique_group',
                                                        'hogql',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                                ),
                                            math_group_type_index: zod
                                                .union([
                                                    zod.union([
                                                        zod.literal(0),
                                                        zod.literal(1),
                                                        zod.literal(2),
                                                        zod.literal(3),
                                                        zod.literal(4),
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Group type index to aggregate over. Required when math is 'unique_group'."
                                                ),
                                            math_hogql: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                                ),
                                            math_property: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                                ),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: start event.'),
                            start_handling: zod.union([zod.enum(['first_seen', 'last_seen']), zod.null()]).optional(),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: when set, reports the percentage of users whose per-user summed/counted value reaches or exceeds this threshold. Only meaningful for sum/count math types.'
                                ),
                            upper_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(
                                            experimentsPartialUpdateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMin
                                        )
                                        .max(
                                            experimentsPartialUpdateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMax
                                        ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). Per-user values above this percentile are clamped to it before aggregation.'
                                ),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().optional(),
        scheduling_config: zod.unknown().optional(),
        allow_unknown_events: zod
            .boolean()
            .optional()
            .describe(
                "Suppresses the validation that rejects metrics referencing events not yet ingested by this project. REQUIRES explicit user confirmation before being set to true — never flip this silently to retry a failed call. The default validation catches typo'd event names and missing instrumentation. Set this to true only when the user has confirmed the event is intentional (e.g. they are about to instrument it)."
            ),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod
            .string()
            .max(experimentsPartialUpdateBodyConclusionCommentMax)
            .nullish()
            .describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().optional(),
        secondary_metrics_ordered_uuids: zod.unknown().optional(),
        only_count_matured_users: zod.boolean().optional(),
        update_feature_flag_params: zod
            .boolean()
            .optional()
            .describe(
                'When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts.'
            ),
    })
    .describe(
        'Full experiment representation for the detail, create, and update endpoints.\n\nExtends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric\ndefinitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side\nfields, and refreshes stale action names while serializing. The list endpoint uses the\nleaner ``ExperimentBasicSerializer`` instead.'
    )

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ExperimentsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Archive an ended experiment.
 *
 * Hides the experiment from the default list view. The experiment can be
 * restored at any time by updating archived=false. When the linked feature
 * flag is still enabled, pass disable_feature_flag=true to also disable and
 * archive it. Returns 400 if the experiment is already archived or has not
 * ended yet.
 */
export const ExperimentsArchiveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
export const ExperimentsCopyToProjectCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
export const ExperimentsDuplicateCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsDuplicateCreateBodyNameMax = 400

export const experimentsDuplicateCreateBodyDescriptionMax = 3000

export const experimentsDuplicateCreateBodyArchivedDefault = false
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneTypeDefault = `event`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwoTypeDefault = `person`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemThreeTypeDefault = `person_metadata`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFourTypeDefault = `element`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFiveTypeDefault = `event_metadata`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSixTypeDefault = `session`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenKeyDefault = `id`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenOperatorDefault = `in`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenTypeDefault = `cohort`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemEightTypeDefault = `recording`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemNineTypeDefault = `log_entry`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnezeroTypeDefault = `group`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneoneTypeDefault = `feature`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoTypeDefault = `flag`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnethreeTypeDefault = `hogql`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefourTypeDefault = `empty`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefiveTypeDefault = `data_warehouse`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesixTypeDefault = `data_warehouse_person_property`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesevenTypeDefault = `error_tracking_issue`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwozeroTypeDefault = `revenue_analytics`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwooneTypeDefault = `workflow_variable`
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsDuplicateCreateBodyMetricsOneItemLowerBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsOneItemLowerBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemUpperBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsOneItemUpperBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMin = 0
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMax = 1

export const experimentsDuplicateCreateBodyAllowUnknownEventsDefault = false
export const experimentsDuplicateCreateBodyConclusionCommentMax = 4000

export const experimentsDuplicateCreateBodyUpdateFeatureFlagParamsDefault = false

export const ExperimentsDuplicateCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsDuplicateCreateBodyNameMax).describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsDuplicateCreateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        feature_flag_key: zod
            .string()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .union([
                zod.object({
                    feature_flag_variants: zod
                        .union([
                            zod.array(
                                zod.object({
                                    key: zod
                                        .string()
                                        .describe(
                                            "Variant key. Exactly one variant in feature_flag_variants must use key 'control' (lowercase, exactly) — that is the baseline used for analysis and the special key the experiment runtime expects. Other variants use keys like 'test', 'variant_a', 'variant_b'. Map natural-language names ('original', 'A', 'baseline') to 'control'."
                                        ),
                                    name: zod
                                        .union([zod.string(), zod.null()])
                                        .optional()
                                        .describe('Human-readable variant name.'),
                                    rollout_percentage: zod.union([zod.number(), zod.null()]).optional(),
                                    split_percent: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                        ),
                                })
                            ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            "Experiment variants. If specified, must include a variant with key 'control' (lowercase). Defaults to a 50/50 control/test split when omitted. Minimum 2, maximum 20."
                        ),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                        ),
                    rollout_percentage: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                        ),
                    variant_notes: zod
                        .union([zod.record(zod.string(), zod.string()), zod.null()])
                        .optional()
                        .describe(
                            'Free-text notes per variant, keyed by variant key. Use to document what each variant does or its reroute URL.'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment parameters JSON. Supported keys include `custom_exposure_filter` and `variant_notes` (free-text notes per variant, keyed by variant key). Flag config keys (`feature_flag_variants`, `rollout_percentage`) are a deprecated input surface kept for compatibility — the linked feature flag is the source of truth, and reads project its current config into this field. Excluded variants live on the top-level `excluded_variants` field, not here.'
            ),
        running_time_calculation: zod
            .union([
                zod.object({
                    exposure_estimate_config: zod
                        .union([
                            zod.object({
                                conversionRateInputType: zod
                                    .enum(['manual', 'automatic'])
                                    .describe(
                                        "'manual' when the baseline value and exposure rate were entered by hand, 'automatic' when derived from live experiment data."
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
                                    .describe(
                                        'Manually entered estimate of users exposed to the experiment per day. Only used in manual mode.'
                                    ),
                                manualMetricType: zod
                                    .union([zod.enum(['funnel', 'mean_count', 'mean_sum_or_avg']), zod.null()])
                                    .optional()
                                    .describe(
                                        'Metric type the manual baseline value refers to. Only used in manual mode.'
                                    ),
                            }),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'How the exposure estimate is configured: manual user-entered values or automatic from live experiment data.'
                        ),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes.'
                        ),
                    recommended_running_time: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe('Estimated number of days needed to reach the recommended sample size.'),
                    recommended_sample_size: zod
                        .union([zod.number(), zod.null()])
                        .optional()
                        .describe('Recommended number of exposed users needed for statistical significance.'),
                }),
                zod.null(),
            ])
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
        secondary_metrics: zod.unknown().optional(),
        saved_metrics_ids: zod
            .array(zod.unknown())
            .nullish()
            .describe(
                "IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary)."
            ),
        filters: zod.unknown().optional(),
        archived: zod
            .boolean()
            .default(experimentsDuplicateCreateBodyArchivedDefault)
            .describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        type: zod
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.null()])
            .optional()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .union([
                zod.object({
                    exposure_config: zod
                        .union([
                            zod.object({
                                event: zod
                                    .union([zod.string(), zod.null()])
                                    .optional()
                                    .describe(
                                        "Custom exposure event name. Required when kind is 'ExperimentEventExposureConfig'."
                                    ),
                                id: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe("Action ID. Required when kind is 'ActionsNode'."),
                                kind: zod
                                    .union([zod.enum(['ExperimentEventExposureConfig', 'ActionsNode']), zod.null()])
                                    .optional()
                                    .describe(
                                        "Defaults to 'ExperimentEventExposureConfig' when omitted. Pass 'ActionsNode' for an action-based exposure."
                                    ),
                                properties: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .union([
                                                        zod.enum([
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
                                                        ]),
                                                        zod.null(),
                                                    ])
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneOperatorDefault
                                                    ),
                                                type: zod
                                                    .literal('event')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneTypeDefault
                                                    )
                                                    .describe('Event properties'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('person')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwoTypeDefault
                                                    )
                                                    .describe('Person properties'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('person_metadata')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemThreeTypeDefault
                                                    )
                                                    .describe(
                                                        'Top-level columns on the persons table (e.g. created_at), not properties JSON'
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('element')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFourTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('event_metadata')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemFiveTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('session')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSixTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                cohort_name: zod.union([zod.string(), zod.null()]).optional(),
                                                key: zod
                                                    .literal('id')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenKeyDefault
                                                    ),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .union([
                                                        zod.enum([
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
                                                        ]),
                                                        zod.null(),
                                                    ])
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenOperatorDefault
                                                    ),
                                                type: zod
                                                    .literal('cohort')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemSevenTypeDefault
                                                    ),
                                                value: zod.number(),
                                            }),
                                            zod.object({
                                                key: zod.union([
                                                    zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                                    zod.string(),
                                                ]),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('recording')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemEightTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('log_entry')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemNineTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                group_key_names: zod
                                                    .union([zod.record(zod.string(), zod.string()), zod.null()])
                                                    .optional(),
                                                group_type_index: zod.union([zod.number(), zod.null()]).optional(),
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('group')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnezeroTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('feature')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOneoneTypeDefault
                                                    )
                                                    .describe('Event property with "$feature/" prepended'),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string().describe('The key should be the flag ID'),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod
                                                    .literal('flag_evaluates_to')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoOperatorDefault
                                                    )
                                                    .describe(
                                                        'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                    ),
                                                type: zod
                                                    .literal('flag')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnetwoTypeDefault
                                                    )
                                                    .describe('Feature flag dependency'),
                                                value: zod
                                                    .union([zod.boolean(), zod.string()])
                                                    .describe('The value can be true, false, or a variant name'),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                type: zod
                                                    .literal('hogql')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnethreeTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                type: zod
                                                    .literal('empty')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefourTypeDefault
                                                    ),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('data_warehouse')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnefiveTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('data_warehouse_person_property')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesixTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('error_tracking_issue')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOnesevenTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('revenue_analytics')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwozeroTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                            zod.object({
                                                key: zod.string(),
                                                label: zod.union([zod.string(), zod.null()]).optional(),
                                                operator: zod.enum([
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
                                                ]),
                                                type: zod
                                                    .literal('workflow_variable')
                                                    .default(
                                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTwooneTypeDefault
                                                    ),
                                                value: zod
                                                    .union([
                                                        zod.array(
                                                            zod.union([zod.string(), zod.number(), zod.boolean()])
                                                        ),
                                                        zod.string(),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            }),
                                        ])
                                    )
                                    .describe(
                                        'Property filters (event, person, and other supported types). Pass an empty array if no filters needed.'
                                    ),
                            }),
                            zod.null(),
                        ])
                        .optional(),
                    filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                    multiple_variant_handling: zod
                        .union([zod.enum(['exclude', 'first_seen']), zod.null()])
                        .optional()
                        .describe(
                            "How to handle entities exposed to multiple variants. 'exclude' (default) drops them from the analysis; 'first_seen' assigns them to the variant from their earliest exposure."
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: denominator source.'),
                            denominator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsDuplicateCreateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsDuplicateCreateBodyMetricsOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsDuplicateCreateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsDuplicateCreateBodyMetricsOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the denominator aggregate. Leave unset for a binomial-style denominator, which is never clamped.'
                                ),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .optional()
                                .describe('Whether higher or lower values indicate success.'),
                            ignore_zeros: zod
                                .union([zod.boolean(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: exclude zero values when computing the winsorization percentile thresholds.'
                                ),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsDuplicateCreateBodyMetricsOneItemKindDefault),
                            lower_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(experimentsDuplicateCreateBodyMetricsOneItemLowerBoundPercentileOneMin)
                                        .max(experimentsDuplicateCreateBodyMetricsOneItemLowerBoundPercentileOneMax),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). Per-user values below this percentile are clamped to it before aggregation.'
                                ),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: numerator source.'),
                            numerator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsDuplicateCreateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsDuplicateCreateBodyMetricsOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsDuplicateCreateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsDuplicateCreateBodyMetricsOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the numerator aggregate, independently of the denominator and each with its own percentile thresholds.'
                                ),
                            retention_window_end: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_start: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .optional(),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            math: zod
                                                .union([
                                                    zod.enum([
                                                        'total',
                                                        'sum',
                                                        'unique_session',
                                                        'min',
                                                        'max',
                                                        'avg',
                                                        'dau',
                                                        'unique_group',
                                                        'hogql',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                                ),
                                            math_group_type_index: zod
                                                .union([
                                                    zod.union([
                                                        zod.literal(0),
                                                        zod.literal(1),
                                                        zod.literal(2),
                                                        zod.literal(3),
                                                        zod.literal(4),
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Group type index to aggregate over. Required when math is 'unique_group'."
                                                ),
                                            math_hogql: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                                ),
                                            math_property: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                                ),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: start event.'),
                            start_handling: zod.union([zod.enum(['first_seen', 'last_seen']), zod.null()]).optional(),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: when set, reports the percentage of users whose per-user summed/counted value reaches or exceeds this threshold. Only meaningful for sum/count math types.'
                                ),
                            upper_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(experimentsDuplicateCreateBodyMetricsOneItemUpperBoundPercentileOneMin)
                                        .max(experimentsDuplicateCreateBodyMetricsOneItemUpperBoundPercentileOneMax),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). Per-user values above this percentile are clamped to it before aggregation.'
                                ),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the read-data-schema tool with query kind 'events' to find available events in the project."
            ),
        metrics_secondary: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: denominator source.'),
                            denominator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the denominator aggregate. Leave unset for a binomial-style denominator, which is never clamped.'
                                ),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .optional()
                                .describe('Whether higher or lower values indicate success.'),
                            ignore_zeros: zod
                                .union([zod.boolean(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: exclude zero values when computing the winsorization percentile thresholds.'
                                ),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemKindDefault),
                            lower_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(
                                            experimentsDuplicateCreateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMin
                                        )
                                        .max(
                                            experimentsDuplicateCreateBodyMetricsSecondaryOneItemLowerBoundPercentileOneMax
                                        ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). Per-user values below this percentile are clamped to it before aggregation.'
                                ),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For ratio metrics: numerator source.'),
                            numerator_outlier_handling: zod
                                .union([
                                    zod.object({
                                        ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
                                        lower_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneLowerBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'
                                            ),
                                        upper_bound_percentile: zod
                                            .union([
                                                zod
                                                    .number()
                                                    .min(
                                                        experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMin
                                                    )
                                                    .max(
                                                        experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOutlierHandlingOneUpperBoundPercentileOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For ratio metrics: winsorization applied to the numerator aggregate, independently of the denominator and each with its own percentile thresholds.'
                                ),
                            retention_window_end: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_start: zod.union([zod.number(), zod.null()]).optional(),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .optional(),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            math: zod
                                                .union([
                                                    zod.enum([
                                                        'total',
                                                        'sum',
                                                        'unique_session',
                                                        'min',
                                                        'max',
                                                        'avg',
                                                        'dau',
                                                        'unique_group',
                                                        'hogql',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                                ),
                                            math_group_type_index: zod
                                                .union([
                                                    zod.union([
                                                        zod.literal(0),
                                                        zod.literal(1),
                                                        zod.literal(2),
                                                        zod.literal(3),
                                                        zod.literal(4),
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Group type index to aggregate over. Required when math is 'unique_group'."
                                                ),
                                            math_hogql: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                                ),
                                            math_property: zod
                                                .union([zod.string(), zod.null()])
                                                .optional()
                                                .describe(
                                                    "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                                ),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        math: zod
                                            .union([
                                                zod.enum([
                                                    'total',
                                                    'sum',
                                                    'unique_session',
                                                    'min',
                                                    'max',
                                                    'avg',
                                                    'dau',
                                                    'unique_group',
                                                    'hogql',
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'."
                                            ),
                                        math_group_type_index: zod
                                            .union([
                                                zod.union([
                                                    zod.literal(0),
                                                    zod.literal(1),
                                                    zod.literal(2),
                                                    zod.literal(3),
                                                    zod.literal(4),
                                                ]),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                "Group type index to aggregate over. Required when math is 'unique_group'."
                                            ),
                                        math_hogql: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum."
                                            ),
                                        math_property: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue')."
                                            ),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod.union([zod.string(), zod.null()]).optional(),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('For retention metrics: start event.'),
                            start_handling: zod.union([zod.enum(['first_seen', 'last_seen']), zod.null()]).optional(),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'For mean metrics: when set, reports the percentage of users whose per-user summed/counted value reaches or exceeds this threshold. Only meaningful for sum/count math types.'
                                ),
                            upper_bound_percentile: zod
                                .union([
                                    zod
                                        .number()
                                        .min(
                                            experimentsDuplicateCreateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMin
                                        )
                                        .max(
                                            experimentsDuplicateCreateBodyMetricsSecondaryOneItemUpperBoundPercentileOneMax
                                        ),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'For mean metrics: winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). Per-user values above this percentile are clamped to it before aggregation.'
                                ),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .optional()
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().optional(),
        scheduling_config: zod.unknown().optional(),
        allow_unknown_events: zod
            .boolean()
            .default(experimentsDuplicateCreateBodyAllowUnknownEventsDefault)
            .describe(
                "Suppresses the validation that rejects metrics referencing events not yet ingested by this project. REQUIRES explicit user confirmation before being set to true — never flip this silently to retry a failed call. The default validation catches typo'd event names and missing instrumentation. Set this to true only when the user has confirmed the event is intentional (e.g. they are about to instrument it)."
            ),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod
            .string()
            .max(experimentsDuplicateCreateBodyConclusionCommentMax)
            .nullish()
            .describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().optional(),
        secondary_metrics_ordered_uuids: zod.unknown().optional(),
        only_count_matured_users: zod.boolean().optional(),
        update_feature_flag_params: zod
            .boolean()
            .default(experimentsDuplicateCreateBodyUpdateFeatureFlagParamsDefault)
            .describe(
                'When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts.'
            ),
    })
    .describe(
        'Full experiment representation for the detail, create, and update endpoints.\n\nExtends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric\ndefinitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side\nfields, and refreshes stale action names while serializing. The list endpoint uses the\nleaner ``ExperimentBasicSerializer`` instead.'
    )

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
export const ExperimentsEndCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsEndCreateBodyConclusionCommentMax = 4000

export const experimentsEndCreateBodyOpenCleanupPrDefault = false

export const ExperimentsEndCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'The conclusion of the experiment.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
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
            "When true, open a draft pull request that removes the experiment's feature-flag code from the linked repository. Only acts for allowlisted teams; ignored otherwise."
        ),
})

/**
 * Launch a draft experiment.
 *
 * Validates the experiment is in draft state, activates its linked feature flag,
 * sets start_date to the current server time, and transitions the experiment to running.
 * Returns 400 if the experiment has already been launched or if the feature flag
 * configuration is invalid (e.g. missing "control" variant or fewer than 2 variants).
 */
export const ExperimentsLaunchCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Pause a running experiment.
 *
 * Deactivates the linked feature flag so it is no longer returned by the
 * /decide endpoint. Users fall back to the application default (typically
 * the control experience), and no new exposure events are recorded (i.e.
 * $feature_flag_called is not fired).
 * Returns 400 if the experiment is not running or is already paused.
 */
export const ExperimentsPauseCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Reset an experiment back to draft state.
 *
 * Clears start/end dates, conclusion, and archived flag. The feature
 * flag is left unchanged — users continue to see their assigned variants.
 *
 * Previously collected events still exist but won't be included in
 * results unless the start date is manually adjusted after re-launch.
 *
 * Returns 400 if the experiment is already in draft state.
 */
export const ExperimentsResetCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Resume a paused experiment.
 *
 * Reactivates the linked feature flag so it is returned by /decide again.
 * Users are re-bucketed deterministically into the same variants they had
 * before the pause, and exposure tracking resumes.
 * Returns 400 if the experiment is not running or is not paused.
 */
export const ExperimentsResumeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
export const ExperimentsShipVariantCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsShipVariantCreateBodyConclusionCommentMax = 4000

export const experimentsShipVariantCreateBodyOpenCleanupPrDefault = false
export const experimentsShipVariantCreateBodyReleaseToEveryoneDefault = false

export const ExperimentsShipVariantCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'The conclusion of the experiment.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
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
            "When true, open a draft pull request that removes the experiment's feature-flag code from the linked repository. Only acts for allowlisted teams; ignored otherwise."
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
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsTimeseriesResultsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsTimeseriesResultsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    fingerprint: zod
        .string()
        .describe(
            "Fingerprint of the metric configuration. Available alongside metric_uuid on each metric in the experiment's metrics array."
        ),
    metric_uuid: zod
        .string()
        .describe(
            "UUID of the metric to fetch timeseries for. Available on each metric in the experiment's metrics array."
        ),
})

/**
 * Unarchive an archived experiment.
 *
 * Restores the experiment to the default list view. Returns 400 if the
 * experiment is not currently archived.
 */
export const ExperimentsUnarchiveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Estimate the recommended sample size and running time for an experiment.
 *
 * Pure statistical calculation — does not read or write any experiment. Pass the metric type, a
 * minimum detectable effect, and either a baseline value or raw baseline statistics. When
 * `exposure_rate_per_day` is provided, the response also includes the estimated running time in days.
 */
export const ExperimentsCalculateRunningTimeCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
                '* `funnel` - funnel\n* `mean_count` - mean_count\n* `mean_sum_or_avg` - mean_sum_or_avg\n* `ratio` - ratio\n* `retention` - retention'
            )
            .describe(
                "Metric type to size for. 'funnel' for conversion rates, 'mean_count' for event counts per user, 'mean_sum_or_avg' for summed property values per user, 'ratio' and 'retention' for ratio-style metrics (both require baseline_stats or an explicit variance).\n\n* `funnel` - funnel\n* `mean_count` - mean_count\n* `mean_sum_or_avg` - mean_sum_or_avg\n* `ratio` - ratio\n* `retention` - retention"
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
                'Baseline metric value: conversion rate as a fraction 0-1 (funnel), average per user (mean), or the ratio (ratio/retention). Provide this or baseline_stats.'
            ),
        variance: zod
            .number()
            .nullish()
            .describe(
                'Pre-computed variance for ratio/retention metrics. Provide this or baseline_stats when metric_type is ratio/retention and baseline_value is given directly.'
            ),
        baseline_stats: zod
            .union([
                zod
                    .object({
                        number_of_samples: zod
                            .number()
                            .min(experimentsCalculateRunningTimeCreateBodyBaselineStatsOneNumberOfSamplesMin)
                            .describe('Number of control-group samples (users/units) observed.'),
                        sum: zod
                            .number()
                            .describe(
                                'Sum of the metric values across the control group (for funnels, the numerator/conversions).'
                            ),
                        sum_squares: zod
                            .number()
                            .default(experimentsCalculateRunningTimeCreateBodyBaselineStatsOneSumSquaresDefault)
                            .describe('Sum of squared metric values. Required for ratio/retention variance.'),
                        denominator_sum: zod
                            .number()
                            .nullish()
                            .describe('Sum of the denominator values. Required for ratio/retention metrics.'),
                        denominator_sum_squares: zod
                            .number()
                            .nullish()
                            .describe('Sum of squared denominator values (ratio/retention variance).'),
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
                        'Raw control-group statistics the calculator uses to derive a baseline value and variance.\n\nSupply this when you want the server to compute the baseline value and (for ratio/retention)\nthe delta-method variance, instead of passing `baseline_value`/`variance` directly.'
                    ),
                zod.null(),
            ])
            .optional()
            .describe('Raw control-group statistics. When provided, the server derives baseline_value and variance.'),
    })
    .describe('Inputs for estimating the recommended sample size and running time of an experiment.')

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsStatsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
