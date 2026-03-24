/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const SurveysListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SurveysListQueryParams = /* @__PURE__ */ zod.object({
    archived: zod.boolean().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const SurveysCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const surveysCreateBodyNameMax = 400

export const surveysCreateBodyQuestionsItemThreeBranchingOneThreeIndexMin = 0

export const surveysCreateBodyQuestionsItemThreeBranchingOneFourResponseValuesOneMin = 0

export const surveysCreateBodyQuestionsItemFourChoicesMin = 2
export const surveysCreateBodyQuestionsItemFourChoicesMax = 20

export const surveysCreateBodyQuestionsItemFourBranchingOneThreeIndexMin = 0

export const surveysCreateBodyQuestionsItemFourBranchingOneFourResponseValuesOneMin = 0

export const surveysCreateBodyQuestionsItemFiveChoicesMin = 2
export const surveysCreateBodyQuestionsItemFiveChoicesMax = 20

export const surveysCreateBodyConditionsOneSeenSurveyWaitPeriodInDaysMin = 0

export const surveysCreateBodyIterationCountMax = 500

export const surveysCreateBodyIterationFrequencyDaysMax = 365

export const surveysCreateBodyCurrentIterationMin = 0
export const surveysCreateBodyCurrentIterationMax = 2147483647

export const surveysCreateBodyResponseSamplingIntervalMin = 0
export const surveysCreateBodyResponseSamplingIntervalMax = 2147483647

export const surveysCreateBodyResponseSamplingLimitMin = 0
export const surveysCreateBodyResponseSamplingLimitMax = 2147483647

export const SurveysCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().min(1).max(surveysCreateBodyNameMax).describe('Survey name.'),
    description: zod.string().optional().describe('Survey description.'),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe('* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api')
        .describe(
            'Survey type.\n\n* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api'
        ),
    schedule: zod
        .union([
            zod
                .enum(['once', 'recurring', 'always'])
                .describe('* `once` - once\n* `recurring` - recurring\n* `always` - always'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)\n\n* `once` - once\n* `recurring` - recurring\n* `always` - always"
        ),
    linked_flag_id: zod.number().nullish().describe('The feature flag linked to this survey.'),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional().describe('An existing targeting flag to use for this survey.'),
    targeting_flag_filters: zod
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
        .nullish()
        .describe(
            "Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 100}]}"
        ),
    remove_targeting_flag: zod
        .boolean()
        .nullish()
        .describe(
            'Set to true to completely remove all targeting filters from the survey, making it visible to all users (subject to other display conditions like URL matching).'
        ),
    questions: zod
        .array(
            zod.union([
                zod.object({
                    type: zod.enum(['open']).describe('* `open` - open'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                }),
                zod.object({
                    type: zod.enum(['link']).describe('* `link` - link'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                    link: zod.string().describe('HTTPS or mailto URL for link questions.'),
                }),
                zod.object({
                    type: zod.enum(['rating']).describe('* `rating` - rating'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                    display: zod
                        .enum(['number', 'emoji'])
                        .describe('* `number` - number\n* `emoji` - emoji')
                        .optional()
                        .describe(
                            "Display format: 'number' shows numeric scale, 'emoji' shows emoji scale.\n\n* `number` - number\n* `emoji` - emoji"
                        ),
                    scale: zod.number().min(1).optional().describe('Rating scale can be one of 3, 5, or 7'),
                    lowerBoundLabel: zod
                        .string()
                        .optional()
                        .describe("Label for the lowest rating (e.g., 'Very Poor')"),
                    upperBoundLabel: zod
                        .string()
                        .optional()
                        .describe("Label for the highest rating (e.g., 'Excellent')"),
                    branching: zod
                        .union([
                            zod.object({
                                type: zod
                                    .enum(['next_question'])
                                    .describe('* `next_question` - next_question')
                                    .describe(
                                        'Continue to the next question in sequence.\n\n* `next_question` - next_question'
                                    ),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['end'])
                                    .describe('* `end` - end')
                                    .describe('End the survey.\n\n* `end` - end'),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['specific_question'])
                                    .describe('* `specific_question` - specific_question')
                                    .describe(
                                        'Jump to a specific question index.\n\n* `specific_question` - specific_question'
                                    ),
                                index: zod
                                    .number()
                                    .min(surveysCreateBodyQuestionsItemThreeBranchingOneThreeIndexMin)
                                    .describe('0-based index of the next question.'),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['response_based'])
                                    .describe('* `response_based` - response_based')
                                    .describe(
                                        'Branch based on the selected or entered response.\n\n* `response_based` - response_based'
                                    ),
                                responseValues: zod
                                    .record(
                                        zod.string(),
                                        zod.union([
                                            zod
                                                .number()
                                                .min(
                                                    surveysCreateBodyQuestionsItemThreeBranchingOneFourResponseValuesOneMin
                                                ),
                                            zod.enum(['end']),
                                        ])
                                    )
                                    .describe("Response-based branching map. Values can be a question index or 'end'."),
                            }),
                        ])
                        .nullish(),
                }),
                zod.object({
                    type: zod.enum(['single_choice']).describe('* `single_choice` - single_choice'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                    choices: zod
                        .array(zod.string())
                        .min(surveysCreateBodyQuestionsItemFourChoicesMin)
                        .max(surveysCreateBodyQuestionsItemFourChoicesMax)
                        .describe(
                            'Array of choice options. Choice indices (0, 1, 2, ...) are used for branching logic.'
                        ),
                    shuffleOptions: zod
                        .boolean()
                        .optional()
                        .describe('Whether to randomize the order of choices for each respondent.'),
                    hasOpenChoice: zod
                        .boolean()
                        .optional()
                        .describe("Whether the final option should be an open-text choice (for example, 'Other')."),
                    branching: zod
                        .union([
                            zod.object({
                                type: zod
                                    .enum(['next_question'])
                                    .describe('* `next_question` - next_question')
                                    .describe(
                                        'Continue to the next question in sequence.\n\n* `next_question` - next_question'
                                    ),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['end'])
                                    .describe('* `end` - end')
                                    .describe('End the survey.\n\n* `end` - end'),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['specific_question'])
                                    .describe('* `specific_question` - specific_question')
                                    .describe(
                                        'Jump to a specific question index.\n\n* `specific_question` - specific_question'
                                    ),
                                index: zod
                                    .number()
                                    .min(surveysCreateBodyQuestionsItemFourBranchingOneThreeIndexMin)
                                    .describe('0-based index of the next question.'),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['response_based'])
                                    .describe('* `response_based` - response_based')
                                    .describe(
                                        'Branch based on the selected or entered response.\n\n* `response_based` - response_based'
                                    ),
                                responseValues: zod
                                    .record(
                                        zod.string(),
                                        zod.union([
                                            zod
                                                .number()
                                                .min(
                                                    surveysCreateBodyQuestionsItemFourBranchingOneFourResponseValuesOneMin
                                                ),
                                            zod.enum(['end']),
                                        ])
                                    )
                                    .describe("Response-based branching map. Values can be a question index or 'end'."),
                            }),
                        ])
                        .nullish(),
                }),
                zod.object({
                    type: zod.enum(['multiple_choice']).describe('* `multiple_choice` - multiple_choice'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                    choices: zod
                        .array(zod.string())
                        .min(surveysCreateBodyQuestionsItemFiveChoicesMin)
                        .max(surveysCreateBodyQuestionsItemFiveChoicesMax)
                        .describe(
                            'Array of choice options. Multiple selections allowed. No branching logic supported.'
                        ),
                    shuffleOptions: zod
                        .boolean()
                        .optional()
                        .describe('Whether to randomize the order of choices for each respondent.'),
                    hasOpenChoice: zod
                        .boolean()
                        .optional()
                        .describe("Whether the final option should be an open-text choice (for example, 'Other')."),
                }),
            ])
        )
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            "type": "next_question"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            "type": "end"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            "type": "response_based",\n            "responseValues": {\n                "responseKey": "value"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            "type": "specific_question",\n            "index": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Any string - allows customers to use their own language keys (e.g., "es", "es-MX", "english", "french")\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            "id": "uuid",\n            "type": "rating",\n            "question": "How satisfied are you?",\n            "lowerBoundLabel": "Not satisfied",\n            "upperBoundLabel": "Very satisfied",\n            "translations": {\n                "es": {\n                    "question": "¿Qué tan satisfecho estás?",\n                    "lowerBoundLabel": "No satisfecho",\n                    "upperBoundLabel": "Muy satisfecho"\n                },\n                "fr": {\n                    "question": "Dans quelle mesure êtes-vous satisfait?"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod
        .object({
            url: zod.string().optional(),
            selector: zod.string().optional(),
            seenSurveyWaitPeriodInDays: zod
                .number()
                .min(surveysCreateBodyConditionsOneSeenSurveyWaitPeriodInDaysMin)
                .optional()
                .describe("Don't show this survey to users who saw any survey in the last x days."),
            urlMatchType: zod
                .enum(['regex', 'not_regex', 'exact', 'is_not', 'icontains', 'not_icontains'])
                .describe(
                    '* `regex` - regex\n* `not_regex` - not_regex\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains'
                )
                .optional()
                .describe(
                    "URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain).\n\n* `regex` - regex\n* `not_regex` - not_regex\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains"
                ),
            events: zod
                .object({
                    repeatedActivation: zod
                        .boolean()
                        .optional()
                        .describe(
                            'Whether to show the survey every time one of the events is triggered (true), or just once (false).'
                        ),
                    values: zod
                        .array(
                            zod.object({
                                name: zod.string().describe('Event name that triggers the survey.'),
                            })
                        )
                        .optional()
                        .describe('Array of event names that trigger the survey.'),
                })
                .optional(),
            deviceTypes: zod
                .array(
                    zod
                        .enum(['Desktop', 'Mobile', 'Tablet'])
                        .describe('* `Desktop` - Desktop\n* `Mobile` - Mobile\n* `Tablet` - Tablet')
                )
                .optional()
                .describe('Device types that should match for this survey to be shown.'),
            deviceTypesMatchType: zod
                .enum(['regex', 'not_regex', 'exact', 'is_not', 'icontains', 'not_icontains'])
                .describe(
                    '* `regex` - regex\n* `not_regex` - not_regex\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains'
                )
                .optional()
                .describe(
                    "URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain).\n\n* `regex` - regex\n* `not_regex` - not_regex\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains"
                ),
            linkedFlagVariant: zod
                .string()
                .optional()
                .describe('The variant of the feature flag linked to this survey.'),
        })
        .nullish()
        .describe('Display and targeting conditions for the survey.'),
    appearance: zod
        .object({
            backgroundColor: zod.string().optional(),
            submitButtonColor: zod.string().optional(),
            textColor: zod.string().optional(),
            submitButtonText: zod.string().optional(),
            submitButtonTextColor: zod.string().optional(),
            descriptionTextColor: zod.string().optional(),
            ratingButtonColor: zod.string().optional(),
            ratingButtonActiveColor: zod.string().optional(),
            ratingButtonHoverColor: zod.string().optional(),
            whiteLabel: zod.boolean().optional(),
            autoDisappear: zod.boolean().optional(),
            displayThankYouMessage: zod.boolean().optional(),
            thankYouMessageHeader: zod.string().optional(),
            thankYouMessageDescription: zod.string().optional(),
            thankYouMessageDescriptionContentType: zod
                .enum(['html', 'text'])
                .optional()
                .describe('* `html` - html\n* `text` - text'),
            thankYouMessageCloseButtonText: zod.string().optional(),
            borderColor: zod.string().optional(),
            placeholder: zod.string().optional(),
            shuffleQuestions: zod.boolean().optional(),
            surveyPopupDelaySeconds: zod.number().optional(),
            widgetType: zod
                .enum(['button', 'tab', 'selector'])
                .optional()
                .describe('* `button` - button\n* `tab` - tab\n* `selector` - selector'),
            widgetSelector: zod.string().optional(),
            widgetLabel: zod.string().optional(),
            widgetColor: zod.string().optional(),
            fontFamily: zod.string().optional(),
            maxWidth: zod.string().optional(),
            zIndex: zod.string().optional(),
            disabledButtonOpacity: zod.string().optional(),
            boxPadding: zod.string().optional(),
        })
        .nullish()
        .describe('Survey appearance customization.'),
    start_date: zod.iso
        .datetime({})
        .nullish()
        .describe(
            "Setting this will launch the survey immediately. Don't add a start_date unless explicitly requested to do so."
        ),
    end_date: zod.iso
        .datetime({})
        .nullish()
        .describe('When the survey stopped being shown to users. Setting this will complete the survey.'),
    archived: zod.boolean().optional().describe('Archive state for the survey.'),
    responses_limit: zod
        .number()
        .nullish()
        .describe('The maximum number of responses before automatically stopping the survey.'),
    iteration_count: zod
        .number()
        .min(1)
        .max(surveysCreateBodyIterationCountMax)
        .nullish()
        .describe(
            "For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule."
        ),
    iteration_frequency_days: zod
        .number()
        .min(1)
        .max(surveysCreateBodyIterationFrequencyDaysMax)
        .nullish()
        .describe(
            'For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.'
        ),
    iteration_start_dates: zod.array(zod.iso.datetime({}).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysCreateBodyCurrentIterationMin)
        .max(surveysCreateBodyCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({}).nullish(),
    response_sampling_start_date: zod.iso.datetime({}).nullish(),
    response_sampling_interval_type: zod
        .union([
            zod.enum(['day', 'week', 'month']).describe('* `day` - day\n* `week` - week\n* `month` - month'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    response_sampling_interval: zod
        .number()
        .min(surveysCreateBodyResponseSamplingIntervalMin)
        .max(surveysCreateBodyResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveysCreateBodyResponseSamplingLimitMin)
        .max(surveysCreateBodyResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().nullish(),
    enable_partial_responses: zod
        .boolean()
        .nullish()
        .describe(
            'When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).'
        ),
    enable_iframe_embedding: zod.boolean().nullish(),
    translations: zod.unknown().nullish(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().nullish(),
})

export const SurveysRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this survey.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SurveysPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this survey.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const surveysPartialUpdateBodyNameMax = 400

export const surveysPartialUpdateBodyQuestionsItemThreeBranchingOneThreeIndexMin = 0

export const surveysPartialUpdateBodyQuestionsItemThreeBranchingOneFourResponseValuesOneMin = 0

export const surveysPartialUpdateBodyQuestionsItemFourChoicesMin = 2
export const surveysPartialUpdateBodyQuestionsItemFourChoicesMax = 20

export const surveysPartialUpdateBodyQuestionsItemFourBranchingOneThreeIndexMin = 0

export const surveysPartialUpdateBodyQuestionsItemFourBranchingOneFourResponseValuesOneMin = 0

export const surveysPartialUpdateBodyQuestionsItemFiveChoicesMin = 2
export const surveysPartialUpdateBodyQuestionsItemFiveChoicesMax = 20

export const surveysPartialUpdateBodyConditionsOneSeenSurveyWaitPeriodInDaysMin = 0

export const surveysPartialUpdateBodyIterationCountMax = 500

export const surveysPartialUpdateBodyIterationFrequencyDaysMax = 365

export const surveysPartialUpdateBodyCurrentIterationMin = 0
export const surveysPartialUpdateBodyCurrentIterationMax = 2147483647

export const surveysPartialUpdateBodyResponseSamplingIntervalMin = 0
export const surveysPartialUpdateBodyResponseSamplingIntervalMax = 2147483647

export const surveysPartialUpdateBodyResponseSamplingLimitMin = 0
export const surveysPartialUpdateBodyResponseSamplingLimitMax = 2147483647

export const SurveysPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().min(1).max(surveysPartialUpdateBodyNameMax).optional().describe('Survey name.'),
    description: zod.string().optional().describe('Survey description.'),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe('* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api')
        .optional()
        .describe(
            'Survey type.\n\n* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api'
        ),
    schedule: zod
        .union([
            zod
                .enum(['once', 'recurring', 'always'])
                .describe('* `once` - once\n* `recurring` - recurring\n* `always` - always'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)\n\n* `once` - once\n* `recurring` - recurring\n* `always` - always"
        ),
    linked_flag_id: zod.number().nullish().describe('The feature flag linked to this survey.'),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional().describe('An existing targeting flag to use for this survey.'),
    targeting_flag_filters: zod
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
        .nullish()
        .describe(
            "Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 100}]}"
        ),
    remove_targeting_flag: zod
        .boolean()
        .nullish()
        .describe(
            'Set to true to completely remove all targeting filters from the survey, making it visible to all users (subject to other display conditions like URL matching).'
        ),
    questions: zod
        .array(
            zod.union([
                zod.object({
                    type: zod.enum(['open']).describe('* `open` - open'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                }),
                zod.object({
                    type: zod.enum(['link']).describe('* `link` - link'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                    link: zod.string().describe('HTTPS or mailto URL for link questions.'),
                }),
                zod.object({
                    type: zod.enum(['rating']).describe('* `rating` - rating'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                    display: zod
                        .enum(['number', 'emoji'])
                        .describe('* `number` - number\n* `emoji` - emoji')
                        .optional()
                        .describe(
                            "Display format: 'number' shows numeric scale, 'emoji' shows emoji scale.\n\n* `number` - number\n* `emoji` - emoji"
                        ),
                    scale: zod.number().min(1).optional().describe('Rating scale can be one of 3, 5, or 7'),
                    lowerBoundLabel: zod
                        .string()
                        .optional()
                        .describe("Label for the lowest rating (e.g., 'Very Poor')"),
                    upperBoundLabel: zod
                        .string()
                        .optional()
                        .describe("Label for the highest rating (e.g., 'Excellent')"),
                    branching: zod
                        .union([
                            zod.object({
                                type: zod
                                    .enum(['next_question'])
                                    .describe('* `next_question` - next_question')
                                    .describe(
                                        'Continue to the next question in sequence.\n\n* `next_question` - next_question'
                                    ),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['end'])
                                    .describe('* `end` - end')
                                    .describe('End the survey.\n\n* `end` - end'),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['specific_question'])
                                    .describe('* `specific_question` - specific_question')
                                    .describe(
                                        'Jump to a specific question index.\n\n* `specific_question` - specific_question'
                                    ),
                                index: zod
                                    .number()
                                    .min(surveysPartialUpdateBodyQuestionsItemThreeBranchingOneThreeIndexMin)
                                    .describe('0-based index of the next question.'),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['response_based'])
                                    .describe('* `response_based` - response_based')
                                    .describe(
                                        'Branch based on the selected or entered response.\n\n* `response_based` - response_based'
                                    ),
                                responseValues: zod
                                    .record(
                                        zod.string(),
                                        zod.union([
                                            zod
                                                .number()
                                                .min(
                                                    surveysPartialUpdateBodyQuestionsItemThreeBranchingOneFourResponseValuesOneMin
                                                ),
                                            zod.enum(['end']),
                                        ])
                                    )
                                    .describe("Response-based branching map. Values can be a question index or 'end'."),
                            }),
                        ])
                        .nullish(),
                }),
                zod.object({
                    type: zod.enum(['single_choice']).describe('* `single_choice` - single_choice'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                    choices: zod
                        .array(zod.string())
                        .min(surveysPartialUpdateBodyQuestionsItemFourChoicesMin)
                        .max(surveysPartialUpdateBodyQuestionsItemFourChoicesMax)
                        .describe(
                            'Array of choice options. Choice indices (0, 1, 2, ...) are used for branching logic.'
                        ),
                    shuffleOptions: zod
                        .boolean()
                        .optional()
                        .describe('Whether to randomize the order of choices for each respondent.'),
                    hasOpenChoice: zod
                        .boolean()
                        .optional()
                        .describe("Whether the final option should be an open-text choice (for example, 'Other')."),
                    branching: zod
                        .union([
                            zod.object({
                                type: zod
                                    .enum(['next_question'])
                                    .describe('* `next_question` - next_question')
                                    .describe(
                                        'Continue to the next question in sequence.\n\n* `next_question` - next_question'
                                    ),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['end'])
                                    .describe('* `end` - end')
                                    .describe('End the survey.\n\n* `end` - end'),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['specific_question'])
                                    .describe('* `specific_question` - specific_question')
                                    .describe(
                                        'Jump to a specific question index.\n\n* `specific_question` - specific_question'
                                    ),
                                index: zod
                                    .number()
                                    .min(surveysPartialUpdateBodyQuestionsItemFourBranchingOneThreeIndexMin)
                                    .describe('0-based index of the next question.'),
                            }),
                            zod.object({
                                type: zod
                                    .enum(['response_based'])
                                    .describe('* `response_based` - response_based')
                                    .describe(
                                        'Branch based on the selected or entered response.\n\n* `response_based` - response_based'
                                    ),
                                responseValues: zod
                                    .record(
                                        zod.string(),
                                        zod.union([
                                            zod
                                                .number()
                                                .min(
                                                    surveysPartialUpdateBodyQuestionsItemFourBranchingOneFourResponseValuesOneMin
                                                ),
                                            zod.enum(['end']),
                                        ])
                                    )
                                    .describe("Response-based branching map. Values can be a question index or 'end'."),
                            }),
                        ])
                        .nullish(),
                }),
                zod.object({
                    type: zod.enum(['multiple_choice']).describe('* `multiple_choice` - multiple_choice'),
                    question: zod.string().describe('Question text shown to respondents.'),
                    description: zod.string().optional().describe('Optional helper text.'),
                    descriptionContentType: zod
                        .enum(['text', 'html'])
                        .describe('* `text` - text\n* `html` - html')
                        .optional()
                        .describe('Format for the description field.\n\n* `text` - text\n* `html` - html'),
                    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
                    buttonText: zod.string().optional().describe('Custom button label.'),
                    choices: zod
                        .array(zod.string())
                        .min(surveysPartialUpdateBodyQuestionsItemFiveChoicesMin)
                        .max(surveysPartialUpdateBodyQuestionsItemFiveChoicesMax)
                        .describe(
                            'Array of choice options. Multiple selections allowed. No branching logic supported.'
                        ),
                    shuffleOptions: zod
                        .boolean()
                        .optional()
                        .describe('Whether to randomize the order of choices for each respondent.'),
                    hasOpenChoice: zod
                        .boolean()
                        .optional()
                        .describe("Whether the final option should be an open-text choice (for example, 'Other')."),
                }),
            ])
        )
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            "type": "next_question"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            "type": "end"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            "type": "response_based",\n            "responseValues": {\n                "responseKey": "value"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            "type": "specific_question",\n            "index": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Any string - allows customers to use their own language keys (e.g., "es", "es-MX", "english", "french")\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            "id": "uuid",\n            "type": "rating",\n            "question": "How satisfied are you?",\n            "lowerBoundLabel": "Not satisfied",\n            "upperBoundLabel": "Very satisfied",\n            "translations": {\n                "es": {\n                    "question": "¿Qué tan satisfecho estás?",\n                    "lowerBoundLabel": "No satisfecho",\n                    "upperBoundLabel": "Muy satisfecho"\n                },\n                "fr": {\n                    "question": "Dans quelle mesure êtes-vous satisfait?"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod
        .object({
            url: zod.string().optional(),
            selector: zod.string().optional(),
            seenSurveyWaitPeriodInDays: zod
                .number()
                .min(surveysPartialUpdateBodyConditionsOneSeenSurveyWaitPeriodInDaysMin)
                .optional()
                .describe("Don't show this survey to users who saw any survey in the last x days."),
            urlMatchType: zod
                .enum(['regex', 'not_regex', 'exact', 'is_not', 'icontains', 'not_icontains'])
                .describe(
                    '* `regex` - regex\n* `not_regex` - not_regex\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains'
                )
                .optional()
                .describe(
                    "URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain).\n\n* `regex` - regex\n* `not_regex` - not_regex\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains"
                ),
            events: zod
                .object({
                    repeatedActivation: zod
                        .boolean()
                        .optional()
                        .describe(
                            'Whether to show the survey every time one of the events is triggered (true), or just once (false).'
                        ),
                    values: zod
                        .array(
                            zod.object({
                                name: zod.string().describe('Event name that triggers the survey.'),
                            })
                        )
                        .optional()
                        .describe('Array of event names that trigger the survey.'),
                })
                .optional(),
            deviceTypes: zod
                .array(
                    zod
                        .enum(['Desktop', 'Mobile', 'Tablet'])
                        .describe('* `Desktop` - Desktop\n* `Mobile` - Mobile\n* `Tablet` - Tablet')
                )
                .optional()
                .describe('Device types that should match for this survey to be shown.'),
            deviceTypesMatchType: zod
                .enum(['regex', 'not_regex', 'exact', 'is_not', 'icontains', 'not_icontains'])
                .describe(
                    '* `regex` - regex\n* `not_regex` - not_regex\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains'
                )
                .optional()
                .describe(
                    "URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain).\n\n* `regex` - regex\n* `not_regex` - not_regex\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains"
                ),
            linkedFlagVariant: zod
                .string()
                .optional()
                .describe('The variant of the feature flag linked to this survey.'),
        })
        .nullish()
        .describe('Display and targeting conditions for the survey.'),
    appearance: zod
        .object({
            backgroundColor: zod.string().optional(),
            submitButtonColor: zod.string().optional(),
            textColor: zod.string().optional(),
            submitButtonText: zod.string().optional(),
            submitButtonTextColor: zod.string().optional(),
            descriptionTextColor: zod.string().optional(),
            ratingButtonColor: zod.string().optional(),
            ratingButtonActiveColor: zod.string().optional(),
            ratingButtonHoverColor: zod.string().optional(),
            whiteLabel: zod.boolean().optional(),
            autoDisappear: zod.boolean().optional(),
            displayThankYouMessage: zod.boolean().optional(),
            thankYouMessageHeader: zod.string().optional(),
            thankYouMessageDescription: zod.string().optional(),
            thankYouMessageDescriptionContentType: zod
                .enum(['html', 'text'])
                .optional()
                .describe('* `html` - html\n* `text` - text'),
            thankYouMessageCloseButtonText: zod.string().optional(),
            borderColor: zod.string().optional(),
            placeholder: zod.string().optional(),
            shuffleQuestions: zod.boolean().optional(),
            surveyPopupDelaySeconds: zod.number().optional(),
            widgetType: zod
                .enum(['button', 'tab', 'selector'])
                .optional()
                .describe('* `button` - button\n* `tab` - tab\n* `selector` - selector'),
            widgetSelector: zod.string().optional(),
            widgetLabel: zod.string().optional(),
            widgetColor: zod.string().optional(),
            fontFamily: zod.string().optional(),
            maxWidth: zod.string().optional(),
            zIndex: zod.string().optional(),
            disabledButtonOpacity: zod.string().optional(),
            boxPadding: zod.string().optional(),
        })
        .nullish()
        .describe('Survey appearance customization.'),
    start_date: zod.iso
        .datetime({})
        .nullish()
        .describe(
            "Setting this will launch the survey immediately. Don't add a start_date unless explicitly requested to do so."
        ),
    end_date: zod.iso
        .datetime({})
        .nullish()
        .describe('When the survey stopped being shown to users. Setting this will complete the survey.'),
    archived: zod.boolean().optional().describe('Archive state for the survey.'),
    responses_limit: zod
        .number()
        .nullish()
        .describe('The maximum number of responses before automatically stopping the survey.'),
    iteration_count: zod
        .number()
        .min(1)
        .max(surveysPartialUpdateBodyIterationCountMax)
        .nullish()
        .describe(
            "For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule."
        ),
    iteration_frequency_days: zod
        .number()
        .min(1)
        .max(surveysPartialUpdateBodyIterationFrequencyDaysMax)
        .nullish()
        .describe(
            'For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.'
        ),
    iteration_start_dates: zod.array(zod.iso.datetime({}).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysPartialUpdateBodyCurrentIterationMin)
        .max(surveysPartialUpdateBodyCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({}).nullish(),
    response_sampling_start_date: zod.iso.datetime({}).nullish(),
    response_sampling_interval_type: zod
        .union([
            zod.enum(['day', 'week', 'month']).describe('* `day` - day\n* `week` - week\n* `month` - month'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    response_sampling_interval: zod
        .number()
        .min(surveysPartialUpdateBodyResponseSamplingIntervalMin)
        .max(surveysPartialUpdateBodyResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveysPartialUpdateBodyResponseSamplingLimitMin)
        .max(surveysPartialUpdateBodyResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().nullish(),
    enable_partial_responses: zod
        .boolean()
        .nullish()
        .describe(
            'When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).'
        ),
    enable_iframe_embedding: zod.boolean().nullish(),
    translations: zod.unknown().nullish(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().nullish(),
})

export const SurveysDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this survey.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Get survey response statistics for a specific survey.

Args:
    date_from: Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
    date_to: Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)
    exclude_archived: Optional boolean to exclude archived responses (default: false, includes archived)

Returns:
    Survey statistics including event counts, unique respondents, and conversion rates
 */
export const SurveysStatsRetrieve2Params = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this survey.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SurveysStatsRetrieve2QueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.iso
        .datetime({})
        .optional()
        .describe('Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)'),
    date_to: zod.iso
        .datetime({})
        .optional()
        .describe('Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)'),
})

/**
 * Get aggregated response statistics across all surveys.

Args:
    date_from: Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
    date_to: Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)

Returns:
    Aggregated statistics across all surveys including total counts and rates
 */
export const SurveysStatsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SurveysStatsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.iso
        .datetime({})
        .optional()
        .describe('Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)'),
    date_to: zod.iso
        .datetime({})
        .optional()
        .describe('Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)'),
})
