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

export const SurveyTypeApi = zod
    .enum(['popover', 'widget', 'external_survey', 'api'])
    .describe('\* `popover` - popover\n\* `widget` - widget\n\* `external_survey` - external survey\n\* `api` - api')

export type SurveyTypeApi = zod.input<typeof SurveyTypeApi>
export type SurveyTypeApiOutput = zod.output<typeof SurveyTypeApi>

export const EvaluationRuntimeEnumApi = zod
    .enum(['server', 'client', 'all'])
    .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All')

export type EvaluationRuntimeEnumApi = zod.input<typeof EvaluationRuntimeEnumApi>
export type EvaluationRuntimeEnumApiOutput = zod.output<typeof EvaluationRuntimeEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

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

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

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

export const ResponseSamplingIntervalTypeEnumApi = zod
    .enum(['day', 'week', 'month'])
    .describe('\* `day` - day\n\* `week` - week\n\* `month` - month')

export type ResponseSamplingIntervalTypeEnumApi = zod.input<typeof ResponseSamplingIntervalTypeEnumApi>
export type ResponseSamplingIntervalTypeEnumApiOutput = zod.output<typeof ResponseSamplingIntervalTypeEnumApi>

export const SearchMatchTypeEnumApi = zod.enum(['exact', 'similar'])

export type SearchMatchTypeEnumApi = zod.input<typeof SearchMatchTypeEnumApi>
export type SearchMatchTypeEnumApiOutput = zod.output<typeof SearchMatchTypeEnumApi>

export const surveyApiNameMax = 400

export const surveyApiResponsesLimitMin = 0
export const surveyApiResponsesLimitMax = 2147483647

export const surveyApiIterationCountMin = 0
export const surveyApiIterationCountMax = 500

export const surveyApiIterationFrequencyDaysMin = 0
export const surveyApiIterationFrequencyDaysMax = 2147483647

export const surveyApiCurrentIterationMin = 0
export const surveyApiCurrentIterationMax = 2147483647

export const surveyApiResponseSamplingIntervalMin = 0
export const surveyApiResponseSamplingIntervalMax = 2147483647

export const surveyApiResponseSamplingLimitMin = 0
export const surveyApiResponseSamplingLimitMax = 2147483647

export const surveyApiBaseLanguageMax = 20

export const SurveyApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(surveyApiNameMax),
        description: zod.string().optional(),
        type: SurveyTypeApi,
        schedule: zod.string().nullish(),
        linked_flag: MinimalFeatureFlagApi,
        linked_flag_id: zod.number().nullish(),
        linked_insight_id: zod.number().nullish(),
        targeting_flag: MinimalFeatureFlagApi,
        internal_targeting_flag: MinimalFeatureFlagApi,
        questions: zod
            .unknown()
            .optional()
            .describe(
                '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Canonical BCP-47-ish strings (e.g., \"es\", \"es-MX\", \"zh-CN\"). Aliases like \"english\" or \"default\" are rejected. The survey\'s `base_language` (default \"en\") declares the language of the untranslated text and cannot also appear as a translation key.\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
            ),
        conditions: zod.record(zod.string(), zod.unknown()).nullable(),
        appearance: zod.unknown().optional(),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        archived: zod.boolean().optional(),
        responses_limit: zod.number().min(surveyApiResponsesLimitMin).max(surveyApiResponsesLimitMax).nullish(),
        feature_flag_keys: zod.array(zod.record(zod.string(), zod.string().nullable())),
        iteration_count: zod.number().min(surveyApiIterationCountMin).max(surveyApiIterationCountMax).nullish(),
        iteration_frequency_days: zod
            .number()
            .min(surveyApiIterationFrequencyDaysMin)
            .max(surveyApiIterationFrequencyDaysMax)
            .nullish(),
        iteration_start_dates: zod.array(zod.iso.datetime({ offset: true }).nullable()).nullish(),
        current_iteration: zod.number().min(surveyApiCurrentIterationMin).max(surveyApiCurrentIterationMax).nullish(),
        current_iteration_start_date: zod.iso.datetime({ offset: true }).nullish(),
        response_sampling_start_date: zod.iso.datetime({ offset: true }).nullish(),
        response_sampling_interval_type: zod
            .union([ResponseSamplingIntervalTypeEnumApi, BlankEnumApi, zod.null()])
            .optional(),
        response_sampling_interval: zod
            .number()
            .min(surveyApiResponseSamplingIntervalMin)
            .max(surveyApiResponseSamplingIntervalMax)
            .nullish(),
        response_sampling_limit: zod
            .number()
            .min(surveyApiResponseSamplingLimitMin)
            .max(surveyApiResponseSamplingLimitMax)
            .nullish(),
        response_sampling_daily_limits: zod.unknown().optional(),
        enable_partial_responses: zod.boolean().nullish(),
        enable_iframe_embedding: zod.boolean().nullish(),
        base_language: zod
            .string()
            .max(surveyApiBaseLanguageMax)
            .optional()
            .describe(
                "BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`."
            ),
        translations: zod.unknown().optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        form_content: zod.unknown().optional(),
        search_match_type: zod
            .union([SearchMatchTypeEnumApi, zod.null()])
            .describe(
                'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
            ),
    })
    .describe('Mixin for serializers to add user access control fields')

export type SurveyApi = zod.input<typeof SurveyApi>
export type SurveyApiOutput = zod.output<typeof SurveyApi>

export const PaginatedSurveyListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SurveyApi),
})

export type PaginatedSurveyListApi = zod.input<typeof PaginatedSurveyListApi>
export type PaginatedSurveyListApiOutput = zod.output<typeof PaginatedSurveyListApi>

export const ScheduleEnumApi = zod
    .enum(['once', 'recurring', 'always'])
    .describe('\* `once` - once\n\* `recurring` - recurring\n\* `always` - always')

export type ScheduleEnumApi = zod.input<typeof ScheduleEnumApi>
export type ScheduleEnumApiOutput = zod.output<typeof ScheduleEnumApi>

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

export const FeatureFlagMultivariateVariantSchemaApi = zod.object({
    key: zod.string().describe('Unique key for this variant.'),
    name: zod.string().optional().describe('Human-readable name for this variant.'),
    rollout_percentage: zod.number().describe('Variant rollout percentage.'),
})

export type FeatureFlagMultivariateVariantSchemaApi = zod.input<typeof FeatureFlagMultivariateVariantSchemaApi>
export type FeatureFlagMultivariateVariantSchemaApiOutput = zod.output<typeof FeatureFlagMultivariateVariantSchemaApi>

export const FeatureFlagMultivariateSchemaApi = zod.object({
    variants: zod
        .array(FeatureFlagMultivariateVariantSchemaApi)
        .describe('Variant definitions for multivariate feature flags.'),
})

export type FeatureFlagMultivariateSchemaApi = zod.input<typeof FeatureFlagMultivariateSchemaApi>
export type FeatureFlagMultivariateSchemaApiOutput = zod.output<typeof FeatureFlagMultivariateSchemaApi>

export const featureFlagFiltersSchemaApiEarlyExitDefault = false

export const FeatureFlagFiltersSchemaApi = zod.object({
    groups: zod
        .array(FeatureFlagConditionGroupSchemaApi)
        .optional()
        .describe('Release condition groups for the feature flag.'),
    multivariate: zod
        .union([FeatureFlagMultivariateSchemaApi, zod.null()])
        .optional()
        .describe('Multivariate configuration for variant-based rollouts.'),
    aggregation_group_type_index: zod.number().nullish().describe('Group type index for group-based feature flags.'),
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
        .default(featureFlagFiltersSchemaApiEarlyExitDefault)
        .describe(
            'When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups.'
        ),
})

export type FeatureFlagFiltersSchemaApi = zod.input<typeof FeatureFlagFiltersSchemaApi>
export type FeatureFlagFiltersSchemaApiOutput = zod.output<typeof FeatureFlagFiltersSchemaApi>

export const SurveyOpenQuestionSchemaTypeEnumApi = zod.enum(['open']).describe('\* `open` - open')

export type SurveyOpenQuestionSchemaTypeEnumApi = zod.input<typeof SurveyOpenQuestionSchemaTypeEnumApi>
export type SurveyOpenQuestionSchemaTypeEnumApiOutput = zod.output<typeof SurveyOpenQuestionSchemaTypeEnumApi>

export const DescriptionContentTypeEnumApi = zod.enum(['html', 'text']).describe('\* `html` - html\n\* `text` - text')

export type DescriptionContentTypeEnumApi = zod.input<typeof DescriptionContentTypeEnumApi>
export type DescriptionContentTypeEnumApiOutput = zod.output<typeof DescriptionContentTypeEnumApi>

export const SurveyOpenQuestionSchemaApi = zod.object({
    id: zod
        .string()
        .optional()
        .describe(
            'Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one.'
        ),
    type: SurveyOpenQuestionSchemaTypeEnumApi,
    question: zod.string().describe('Question text shown to respondents.'),
    description: zod.string().optional().describe('Optional helper text.'),
    descriptionContentType: DescriptionContentTypeEnumApi.optional().describe(
        'Format for the description field.\n\n\* `text` - text\n\* `html` - html'
    ),
    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
    buttonText: zod.string().optional().describe('Custom button label.'),
})

export type SurveyOpenQuestionSchemaApi = zod.input<typeof SurveyOpenQuestionSchemaApi>
export type SurveyOpenQuestionSchemaApiOutput = zod.output<typeof SurveyOpenQuestionSchemaApi>

export const SurveyLinkQuestionSchemaTypeEnumApi = zod.enum(['link']).describe('\* `link` - link')

export type SurveyLinkQuestionSchemaTypeEnumApi = zod.input<typeof SurveyLinkQuestionSchemaTypeEnumApi>
export type SurveyLinkQuestionSchemaTypeEnumApiOutput = zod.output<typeof SurveyLinkQuestionSchemaTypeEnumApi>

export const SurveyLinkQuestionSchemaApi = zod.object({
    id: zod
        .string()
        .optional()
        .describe(
            'Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one.'
        ),
    type: SurveyLinkQuestionSchemaTypeEnumApi,
    question: zod.string().describe('Question text shown to respondents.'),
    description: zod.string().optional().describe('Optional helper text.'),
    descriptionContentType: DescriptionContentTypeEnumApi.optional().describe(
        'Format for the description field.\n\n\* `text` - text\n\* `html` - html'
    ),
    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
    buttonText: zod.string().optional().describe('Custom button label.'),
    link: zod.string().describe('HTTPS or mailto URL for link questions.'),
})

export type SurveyLinkQuestionSchemaApi = zod.input<typeof SurveyLinkQuestionSchemaApi>
export type SurveyLinkQuestionSchemaApiOutput = zod.output<typeof SurveyLinkQuestionSchemaApi>

export const SurveyRatingQuestionSchemaTypeEnumApi = zod.enum(['rating']).describe('\* `rating` - rating')

export type SurveyRatingQuestionSchemaTypeEnumApi = zod.input<typeof SurveyRatingQuestionSchemaTypeEnumApi>
export type SurveyRatingQuestionSchemaTypeEnumApiOutput = zod.output<typeof SurveyRatingQuestionSchemaTypeEnumApi>

export const SurveyRatingQuestionSchemaDisplayEnumApi = zod
    .enum(['number', 'emoji'])
    .describe('\* `number` - number\n\* `emoji` - emoji')

export type SurveyRatingQuestionSchemaDisplayEnumApi = zod.input<typeof SurveyRatingQuestionSchemaDisplayEnumApi>
export type SurveyRatingQuestionSchemaDisplayEnumApiOutput = zod.output<typeof SurveyRatingQuestionSchemaDisplayEnumApi>

export const SurveyNextQuestionBranchingTypeEnumApi = zod
    .enum(['next_question'])
    .describe('\* `next_question` - next_question')

export type SurveyNextQuestionBranchingTypeEnumApi = zod.input<typeof SurveyNextQuestionBranchingTypeEnumApi>
export type SurveyNextQuestionBranchingTypeEnumApiOutput = zod.output<typeof SurveyNextQuestionBranchingTypeEnumApi>

export const SurveyNextQuestionBranchingApi = zod.object({
    type: SurveyNextQuestionBranchingTypeEnumApi.describe(
        'Continue to the next question in sequence.\n\n\* `next_question` - next_question'
    ),
})

export type SurveyNextQuestionBranchingApi = zod.input<typeof SurveyNextQuestionBranchingApi>
export type SurveyNextQuestionBranchingApiOutput = zod.output<typeof SurveyNextQuestionBranchingApi>

export const SurveyEndBranchingTypeEnumApi = zod.enum(['end']).describe('\* `end` - end')

export type SurveyEndBranchingTypeEnumApi = zod.input<typeof SurveyEndBranchingTypeEnumApi>
export type SurveyEndBranchingTypeEnumApiOutput = zod.output<typeof SurveyEndBranchingTypeEnumApi>

export const SurveyEndBranchingApi = zod.object({
    type: SurveyEndBranchingTypeEnumApi.describe('End the survey.\n\n\* `end` - end'),
})

export type SurveyEndBranchingApi = zod.input<typeof SurveyEndBranchingApi>
export type SurveyEndBranchingApiOutput = zod.output<typeof SurveyEndBranchingApi>

export const SurveySpecificQuestionBranchingTypeEnumApi = zod
    .enum(['specific_question'])
    .describe('\* `specific_question` - specific_question')

export type SurveySpecificQuestionBranchingTypeEnumApi = zod.input<typeof SurveySpecificQuestionBranchingTypeEnumApi>
export type SurveySpecificQuestionBranchingTypeEnumApiOutput = zod.output<
    typeof SurveySpecificQuestionBranchingTypeEnumApi
>

export const surveySpecificQuestionBranchingApiIndexMin = 0

export const SurveySpecificQuestionBranchingApi = zod.object({
    type: SurveySpecificQuestionBranchingTypeEnumApi.describe(
        'Jump to a specific question index.\n\n\* `specific_question` - specific_question'
    ),
    index: zod.number().min(surveySpecificQuestionBranchingApiIndexMin).describe('0-based index of the next question.'),
})

export type SurveySpecificQuestionBranchingApi = zod.input<typeof SurveySpecificQuestionBranchingApi>
export type SurveySpecificQuestionBranchingApiOutput = zod.output<typeof SurveySpecificQuestionBranchingApi>

export const SurveyResponseBasedBranchingTypeEnumApi = zod
    .enum(['response_based'])
    .describe('\* `response_based` - response_based')

export type SurveyResponseBasedBranchingTypeEnumApi = zod.input<typeof SurveyResponseBasedBranchingTypeEnumApi>
export type SurveyResponseBasedBranchingTypeEnumApiOutput = zod.output<typeof SurveyResponseBasedBranchingTypeEnumApi>

export const surveyResponseBasedBranchingApiResponseValuesOneMin = 0

export const SurveyResponseBasedBranchingApi = zod.object({
    type: SurveyResponseBasedBranchingTypeEnumApi.describe(
        'Branch based on the selected or entered response.\n\n\* `response_based` - response_based'
    ),
    responseValues: zod
        .record(
            zod.string(),
            zod.union([zod.number().min(surveyResponseBasedBranchingApiResponseValuesOneMin), zod.enum(['end'])])
        )
        .describe("Response-based branching map. Values can be a question index or 'end'."),
})

export type SurveyResponseBasedBranchingApi = zod.input<typeof SurveyResponseBasedBranchingApi>
export type SurveyResponseBasedBranchingApiOutput = zod.output<typeof SurveyResponseBasedBranchingApi>

export const SurveyBranchingSchemaApi = zod.union([
    SurveyNextQuestionBranchingApi,
    SurveyEndBranchingApi,
    SurveySpecificQuestionBranchingApi,
    SurveyResponseBasedBranchingApi,
])

export type SurveyBranchingSchemaApi = zod.input<typeof SurveyBranchingSchemaApi>
export type SurveyBranchingSchemaApiOutput = zod.output<typeof SurveyBranchingSchemaApi>

export const SurveyRatingQuestionSchemaApi = zod.object({
    id: zod
        .string()
        .optional()
        .describe(
            'Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one.'
        ),
    type: SurveyRatingQuestionSchemaTypeEnumApi,
    question: zod.string().describe('Question text shown to respondents.'),
    description: zod.string().optional().describe('Optional helper text.'),
    descriptionContentType: DescriptionContentTypeEnumApi.optional().describe(
        'Format for the description field.\n\n\* `text` - text\n\* `html` - html'
    ),
    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
    buttonText: zod.string().optional().describe('Custom button label.'),
    display: SurveyRatingQuestionSchemaDisplayEnumApi.optional().describe(
        "Display format: 'number' shows numeric scale, 'emoji' shows emoji scale.\n\n\* `number` - number\n\* `emoji` - emoji"
    ),
    scale: zod.number().min(1).optional().describe('Rating scale can be one of 3, 5, or 7'),
    lowerBoundLabel: zod.string().optional().describe("Label for the lowest rating (e.g., 'Very Poor')"),
    upperBoundLabel: zod.string().optional().describe("Label for the highest rating (e.g., 'Excellent')"),
    branching: zod.union([SurveyBranchingSchemaApi, zod.null()]).optional(),
})

export type SurveyRatingQuestionSchemaApi = zod.input<typeof SurveyRatingQuestionSchemaApi>
export type SurveyRatingQuestionSchemaApiOutput = zod.output<typeof SurveyRatingQuestionSchemaApi>

export const SurveySingleChoiceQuestionSchemaTypeEnumApi = zod
    .enum(['single_choice'])
    .describe('\* `single_choice` - single_choice')

export type SurveySingleChoiceQuestionSchemaTypeEnumApi = zod.input<typeof SurveySingleChoiceQuestionSchemaTypeEnumApi>
export type SurveySingleChoiceQuestionSchemaTypeEnumApiOutput = zod.output<
    typeof SurveySingleChoiceQuestionSchemaTypeEnumApi
>

export const surveySingleChoiceQuestionSchemaApiChoicesMin = 2
export const surveySingleChoiceQuestionSchemaApiChoicesMax = 20

export const SurveySingleChoiceQuestionSchemaApi = zod.object({
    id: zod
        .string()
        .optional()
        .describe(
            'Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one.'
        ),
    type: SurveySingleChoiceQuestionSchemaTypeEnumApi,
    question: zod.string().describe('Question text shown to respondents.'),
    description: zod.string().optional().describe('Optional helper text.'),
    descriptionContentType: DescriptionContentTypeEnumApi.optional().describe(
        'Format for the description field.\n\n\* `text` - text\n\* `html` - html'
    ),
    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
    buttonText: zod.string().optional().describe('Custom button label.'),
    choices: zod
        .array(zod.string())
        .min(surveySingleChoiceQuestionSchemaApiChoicesMin)
        .max(surveySingleChoiceQuestionSchemaApiChoicesMax)
        .describe('Array of choice options. Choice indices (0, 1, 2, ...) are used for branching logic.'),
    shuffleOptions: zod.boolean().optional().describe('Whether to randomize the order of choices for each respondent.'),
    hasOpenChoice: zod
        .boolean()
        .optional()
        .describe("Whether the final option should be an open-text choice (for example, 'Other')."),
    branching: zod.union([SurveyBranchingSchemaApi, zod.null()]).optional(),
})

export type SurveySingleChoiceQuestionSchemaApi = zod.input<typeof SurveySingleChoiceQuestionSchemaApi>
export type SurveySingleChoiceQuestionSchemaApiOutput = zod.output<typeof SurveySingleChoiceQuestionSchemaApi>

export const SurveyMultipleChoiceQuestionSchemaTypeEnumApi = zod
    .enum(['multiple_choice'])
    .describe('\* `multiple_choice` - multiple_choice')

export type SurveyMultipleChoiceQuestionSchemaTypeEnumApi = zod.input<
    typeof SurveyMultipleChoiceQuestionSchemaTypeEnumApi
>
export type SurveyMultipleChoiceQuestionSchemaTypeEnumApiOutput = zod.output<
    typeof SurveyMultipleChoiceQuestionSchemaTypeEnumApi
>

export const surveyMultipleChoiceQuestionSchemaApiChoicesMin = 2
export const surveyMultipleChoiceQuestionSchemaApiChoicesMax = 20

export const SurveyMultipleChoiceQuestionSchemaApi = zod.object({
    id: zod
        .string()
        .optional()
        .describe(
            'Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one.'
        ),
    type: SurveyMultipleChoiceQuestionSchemaTypeEnumApi,
    question: zod.string().describe('Question text shown to respondents.'),
    description: zod.string().optional().describe('Optional helper text.'),
    descriptionContentType: DescriptionContentTypeEnumApi.optional().describe(
        'Format for the description field.\n\n\* `text` - text\n\* `html` - html'
    ),
    optional: zod.boolean().optional().describe('Whether respondents may skip this question.'),
    buttonText: zod.string().optional().describe('Custom button label.'),
    choices: zod
        .array(zod.string())
        .min(surveyMultipleChoiceQuestionSchemaApiChoicesMin)
        .max(surveyMultipleChoiceQuestionSchemaApiChoicesMax)
        .describe('Array of choice options. Multiple selections allowed. No branching logic supported.'),
    shuffleOptions: zod.boolean().optional().describe('Whether to randomize the order of choices for each respondent.'),
    hasOpenChoice: zod
        .boolean()
        .optional()
        .describe("Whether the final option should be an open-text choice (for example, 'Other')."),
})

export type SurveyMultipleChoiceQuestionSchemaApi = zod.input<typeof SurveyMultipleChoiceQuestionSchemaApi>
export type SurveyMultipleChoiceQuestionSchemaApiOutput = zod.output<typeof SurveyMultipleChoiceQuestionSchemaApi>

export const SurveyQuestionInputSchemaApi = zod.union([
    SurveyOpenQuestionSchemaApi,
    SurveyLinkQuestionSchemaApi,
    SurveyRatingQuestionSchemaApi,
    SurveySingleChoiceQuestionSchemaApi,
    SurveyMultipleChoiceQuestionSchemaApi,
])

export type SurveyQuestionInputSchemaApi = zod.input<typeof SurveyQuestionInputSchemaApi>
export type SurveyQuestionInputSchemaApiOutput = zod.output<typeof SurveyQuestionInputSchemaApi>

export const SurveyMatchTypeEnumApi = zod
    .enum(['regex', 'not_regex', 'exact', 'is_not', 'icontains', 'not_icontains'])
    .describe(
        '\* `regex` - regex\n\* `not_regex` - not_regex\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains'
    )

export type SurveyMatchTypeEnumApi = zod.input<typeof SurveyMatchTypeEnumApi>
export type SurveyMatchTypeEnumApiOutput = zod.output<typeof SurveyMatchTypeEnumApi>

export const SurveyConditionEventValueSchemaApi = zod.object({
    name: zod.string().describe('Event name that triggers the survey.'),
})

export type SurveyConditionEventValueSchemaApi = zod.input<typeof SurveyConditionEventValueSchemaApi>
export type SurveyConditionEventValueSchemaApiOutput = zod.output<typeof SurveyConditionEventValueSchemaApi>

export const SurveyEventsConditionSchemaApi = zod.object({
    repeatedActivation: zod
        .boolean()
        .optional()
        .describe('Whether to show the survey every time one of the events is triggered (true), or just once (false).'),
    values: zod
        .array(SurveyConditionEventValueSchemaApi)
        .optional()
        .describe('Array of event names that trigger the survey.'),
})

export type SurveyEventsConditionSchemaApi = zod.input<typeof SurveyEventsConditionSchemaApi>
export type SurveyEventsConditionSchemaApiOutput = zod.output<typeof SurveyEventsConditionSchemaApi>

export const DeviceTypesEnumApi = zod
    .enum(['Desktop', 'Mobile', 'Tablet'])
    .describe('\* `Desktop` - Desktop\n\* `Mobile` - Mobile\n\* `Tablet` - Tablet')

export type DeviceTypesEnumApi = zod.input<typeof DeviceTypesEnumApi>
export type DeviceTypesEnumApiOutput = zod.output<typeof DeviceTypesEnumApi>

export const surveyConditionsSchemaApiSeenSurveyWaitPeriodInDaysMin = 0

export const SurveyConditionsSchemaApi = zod.object({
    url: zod.string().optional(),
    selector: zod.string().optional(),
    seenSurveyWaitPeriodInDays: zod
        .number()
        .min(surveyConditionsSchemaApiSeenSurveyWaitPeriodInDaysMin)
        .optional()
        .describe("Don't show this survey to users who saw any survey in the last x days."),
    urlMatchType: SurveyMatchTypeEnumApi.optional().describe(
        "URL\/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain).\n\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains"
    ),
    events: SurveyEventsConditionSchemaApi.optional(),
    deviceTypes: zod
        .array(DeviceTypesEnumApi)
        .optional()
        .describe('Device types that should match for this survey to be shown.'),
    deviceTypesMatchType: SurveyMatchTypeEnumApi.optional().describe(
        "URL\/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain).\n\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains"
    ),
    linkedFlagVariant: zod.string().optional().describe('The variant of the feature flag linked to this survey.'),
})

export type SurveyConditionsSchemaApi = zod.input<typeof SurveyConditionsSchemaApi>
export type SurveyConditionsSchemaApiOutput = zod.output<typeof SurveyConditionsSchemaApi>

export const WidgetTypeEnumApi = zod
    .enum(['button', 'tab', 'selector'])
    .describe('\* `button` - button\n\* `tab` - tab\n\* `selector` - selector')

export type WidgetTypeEnumApi = zod.input<typeof WidgetTypeEnumApi>
export type WidgetTypeEnumApiOutput = zod.output<typeof WidgetTypeEnumApi>

export const SurveyAppearanceSchemaApi = zod.object({
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
    thankYouMessageDescriptionContentType: DescriptionContentTypeEnumApi.optional(),
    thankYouMessageCloseButtonText: zod.string().optional(),
    borderColor: zod.string().optional(),
    placeholder: zod.string().optional(),
    shuffleQuestions: zod.boolean().optional(),
    surveyPopupDelaySeconds: zod.number().optional(),
    allowGoBack: zod
        .boolean()
        .optional()
        .describe(
            "Whether to show a 'Back' button on web surveys after the first question, letting respondents return to a previously visited question. Defaults to false."
        ),
    backButtonText: zod
        .string()
        .optional()
        .describe("Optional override for the back button label. Defaults to 'Back'."),
    widgetType: WidgetTypeEnumApi.optional(),
    widgetSelector: zod.string().optional(),
    widgetLabel: zod.string().optional(),
    widgetColor: zod.string().optional(),
    fontFamily: zod.string().optional(),
    maxWidth: zod.string().optional(),
    zIndex: zod.string().optional(),
    disabledButtonOpacity: zod.string().optional(),
    boxPadding: zod.string().optional(),
})

export type SurveyAppearanceSchemaApi = zod.input<typeof SurveyAppearanceSchemaApi>
export type SurveyAppearanceSchemaApiOutput = zod.output<typeof SurveyAppearanceSchemaApi>

export const surveySerializerCreateUpdateOnlySchemaApiNameMax = 400

export const surveySerializerCreateUpdateOnlySchemaApiIterationCountMax = 500

export const surveySerializerCreateUpdateOnlySchemaApiIterationFrequencyDaysMax = 365

export const surveySerializerCreateUpdateOnlySchemaApiCurrentIterationMin = 0
export const surveySerializerCreateUpdateOnlySchemaApiCurrentIterationMax = 2147483647

export const surveySerializerCreateUpdateOnlySchemaApiResponseSamplingIntervalMin = 0
export const surveySerializerCreateUpdateOnlySchemaApiResponseSamplingIntervalMax = 2147483647

export const surveySerializerCreateUpdateOnlySchemaApiResponseSamplingLimitMin = 0
export const surveySerializerCreateUpdateOnlySchemaApiResponseSamplingLimitMax = 2147483647

export const surveySerializerCreateUpdateOnlySchemaApiBaseLanguageMax = 20

export const SurveySerializerCreateUpdateOnlySchemaApi = zod.object({
    id: zod.uuid(),
    name: zod.string().min(1).max(surveySerializerCreateUpdateOnlySchemaApiNameMax).describe('Survey name.'),
    description: zod.string().optional().describe('Survey description.'),
    type: SurveyTypeApi.describe(
        'Survey type.\n\n\* `popover` - popover\n\* `widget` - widget\n\* `external_survey` - external survey\n\* `api` - api'
    ),
    schedule: zod
        .union([ScheduleEnumApi, zod.null()])
        .optional()
        .describe(
            "Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)\n\n\* `once` - once\n\* `recurring` - recurring\n\* `always` - always"
        ),
    linked_flag: MinimalFeatureFlagApi,
    linked_flag_id: zod.number().nullish().describe('The feature flag linked to this survey.'),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional().describe('An existing targeting flag to use for this survey.'),
    targeting_flag: MinimalFeatureFlagApi,
    internal_targeting_flag: MinimalFeatureFlagApi,
    targeting_flag_filters: zod
        .union([FeatureFlagFiltersSchemaApi, zod.null()])
        .optional()
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
        .array(SurveyQuestionInputSchemaApi)
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Canonical BCP-47-ish strings (e.g., \"es\", \"es-MX\", \"zh-CN\"). Aliases like \"english\" or \"default\" are rejected. The survey\'s `base_language` (default \"en\") declares the language of the untranslated text and cannot also appear as a translation key.\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod
        .union([SurveyConditionsSchemaApi, zod.null()])
        .optional()
        .describe('Display and targeting conditions for the survey.'),
    appearance: zod
        .union([SurveyAppearanceSchemaApi, zod.null()])
        .optional()
        .describe('Survey appearance customization.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    start_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            "Setting this will launch the survey immediately. Don't add a start_date unless explicitly requested to do so."
        ),
    end_date: zod.iso
        .datetime({ offset: true })
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
        .max(surveySerializerCreateUpdateOnlySchemaApiIterationCountMax)
        .nullish()
        .describe(
            "For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule."
        ),
    iteration_frequency_days: zod
        .number()
        .min(1)
        .max(surveySerializerCreateUpdateOnlySchemaApiIterationFrequencyDaysMax)
        .nullish()
        .describe(
            'For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.'
        ),
    iteration_start_dates: zod.array(zod.iso.datetime({ offset: true }).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveySerializerCreateUpdateOnlySchemaApiCurrentIterationMin)
        .max(surveySerializerCreateUpdateOnlySchemaApiCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_interval_type: zod
        .union([ResponseSamplingIntervalTypeEnumApi, BlankEnumApi, zod.null()])
        .optional(),
    response_sampling_interval: zod
        .number()
        .min(surveySerializerCreateUpdateOnlySchemaApiResponseSamplingIntervalMin)
        .max(surveySerializerCreateUpdateOnlySchemaApiResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveySerializerCreateUpdateOnlySchemaApiResponseSamplingLimitMin)
        .max(surveySerializerCreateUpdateOnlySchemaApiResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().optional(),
    enable_partial_responses: zod
        .boolean()
        .nullish()
        .describe(
            'When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).'
        ),
    enable_iframe_embedding: zod.boolean().nullish(),
    base_language: zod
        .string()
        .max(surveySerializerCreateUpdateOnlySchemaApiBaseLanguageMax)
        .optional()
        .describe(
            "BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`."
        ),
    translations: zod.unknown().optional(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().optional(),
})

export type SurveySerializerCreateUpdateOnlySchemaApi = zod.input<typeof SurveySerializerCreateUpdateOnlySchemaApi>
export type SurveySerializerCreateUpdateOnlySchemaApiOutput = zod.output<
    typeof SurveySerializerCreateUpdateOnlySchemaApi
>

export const surveySerializerCreateUpdateOnlyApiNameMax = 400

export const surveySerializerCreateUpdateOnlyApiResponsesLimitMin = 0
export const surveySerializerCreateUpdateOnlyApiResponsesLimitMax = 2147483647

export const surveySerializerCreateUpdateOnlyApiIterationCountMin = 0
export const surveySerializerCreateUpdateOnlyApiIterationCountMax = 500

export const surveySerializerCreateUpdateOnlyApiIterationFrequencyDaysMin = 0
export const surveySerializerCreateUpdateOnlyApiIterationFrequencyDaysMax = 2147483647

export const surveySerializerCreateUpdateOnlyApiCurrentIterationMin = 0
export const surveySerializerCreateUpdateOnlyApiCurrentIterationMax = 2147483647

export const surveySerializerCreateUpdateOnlyApiResponseSamplingIntervalMin = 0
export const surveySerializerCreateUpdateOnlyApiResponseSamplingIntervalMax = 2147483647

export const surveySerializerCreateUpdateOnlyApiResponseSamplingLimitMin = 0
export const surveySerializerCreateUpdateOnlyApiResponseSamplingLimitMax = 2147483647

export const surveySerializerCreateUpdateOnlyApiBaseLanguageMax = 20

export const SurveySerializerCreateUpdateOnlyApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(surveySerializerCreateUpdateOnlyApiNameMax),
    description: zod.string().optional(),
    type: SurveyTypeApi,
    schedule: zod.string().nullish(),
    linked_flag: MinimalFeatureFlagApi,
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
    targeting_flag: MinimalFeatureFlagApi,
    internal_targeting_flag: MinimalFeatureFlagApi,
    targeting_flag_filters: zod.unknown().optional(),
    remove_targeting_flag: zod.boolean().nullish(),
    questions: zod
        .unknown()
        .optional()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Canonical BCP-47-ish strings (e.g., \"es\", \"es-MX\", \"zh-CN\"). Aliases like \"english\" or \"default\" are rejected. The survey\'s `base_language` (default \"en\") declares the language of the untranslated text and cannot also appear as a translation key.\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod.unknown().optional(),
    appearance: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    start_date: zod.iso.datetime({ offset: true }).nullish(),
    end_date: zod.iso.datetime({ offset: true }).nullish(),
    archived: zod.boolean().optional(),
    responses_limit: zod
        .number()
        .min(surveySerializerCreateUpdateOnlyApiResponsesLimitMin)
        .max(surveySerializerCreateUpdateOnlyApiResponsesLimitMax)
        .nullish(),
    iteration_count: zod
        .number()
        .min(surveySerializerCreateUpdateOnlyApiIterationCountMin)
        .max(surveySerializerCreateUpdateOnlyApiIterationCountMax)
        .nullish(),
    iteration_frequency_days: zod
        .number()
        .min(surveySerializerCreateUpdateOnlyApiIterationFrequencyDaysMin)
        .max(surveySerializerCreateUpdateOnlyApiIterationFrequencyDaysMax)
        .nullish(),
    iteration_start_dates: zod.array(zod.iso.datetime({ offset: true }).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveySerializerCreateUpdateOnlyApiCurrentIterationMin)
        .max(surveySerializerCreateUpdateOnlyApiCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_interval_type: zod
        .union([ResponseSamplingIntervalTypeEnumApi, BlankEnumApi, zod.null()])
        .optional(),
    response_sampling_interval: zod
        .number()
        .min(surveySerializerCreateUpdateOnlyApiResponseSamplingIntervalMin)
        .max(surveySerializerCreateUpdateOnlyApiResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveySerializerCreateUpdateOnlyApiResponseSamplingLimitMin)
        .max(surveySerializerCreateUpdateOnlyApiResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().optional(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    base_language: zod
        .string()
        .max(surveySerializerCreateUpdateOnlyApiBaseLanguageMax)
        .optional()
        .describe(
            "BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`."
        ),
    translations: zod.unknown().optional(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().optional(),
})

export type SurveySerializerCreateUpdateOnlyApi = zod.input<typeof SurveySerializerCreateUpdateOnlyApi>
export type SurveySerializerCreateUpdateOnlyApiOutput = zod.output<typeof SurveySerializerCreateUpdateOnlyApi>

export const patchedSurveySerializerCreateUpdateOnlySchemaApiNameMax = 400

export const patchedSurveySerializerCreateUpdateOnlySchemaApiIterationCountMax = 500

export const patchedSurveySerializerCreateUpdateOnlySchemaApiIterationFrequencyDaysMax = 365

export const patchedSurveySerializerCreateUpdateOnlySchemaApiCurrentIterationMin = 0
export const patchedSurveySerializerCreateUpdateOnlySchemaApiCurrentIterationMax = 2147483647

export const patchedSurveySerializerCreateUpdateOnlySchemaApiResponseSamplingIntervalMin = 0
export const patchedSurveySerializerCreateUpdateOnlySchemaApiResponseSamplingIntervalMax = 2147483647

export const patchedSurveySerializerCreateUpdateOnlySchemaApiResponseSamplingLimitMin = 0
export const patchedSurveySerializerCreateUpdateOnlySchemaApiResponseSamplingLimitMax = 2147483647

export const patchedSurveySerializerCreateUpdateOnlySchemaApiBaseLanguageMax = 20

export const PatchedSurveySerializerCreateUpdateOnlySchemaApi = zod.object({
    id: zod.uuid().optional(),
    name: zod
        .string()
        .min(1)
        .max(patchedSurveySerializerCreateUpdateOnlySchemaApiNameMax)
        .optional()
        .describe('Survey name.'),
    description: zod.string().optional().describe('Survey description.'),
    type: SurveyTypeApi.optional().describe(
        'Survey type.\n\n\* `popover` - popover\n\* `widget` - widget\n\* `external_survey` - external survey\n\* `api` - api'
    ),
    schedule: zod
        .union([ScheduleEnumApi, zod.null()])
        .optional()
        .describe(
            "Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)\n\n\* `once` - once\n\* `recurring` - recurring\n\* `always` - always"
        ),
    linked_flag: MinimalFeatureFlagApi.optional(),
    linked_flag_id: zod.number().nullish().describe('The feature flag linked to this survey.'),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional().describe('An existing targeting flag to use for this survey.'),
    targeting_flag: MinimalFeatureFlagApi.optional(),
    internal_targeting_flag: MinimalFeatureFlagApi.optional(),
    targeting_flag_filters: zod
        .union([FeatureFlagFiltersSchemaApi, zod.null()])
        .optional()
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
        .array(SurveyQuestionInputSchemaApi)
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Canonical BCP-47-ish strings (e.g., \"es\", \"es-MX\", \"zh-CN\"). Aliases like \"english\" or \"default\" are rejected. The survey\'s `base_language` (default \"en\") declares the language of the untranslated text and cannot also appear as a translation key.\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod
        .union([SurveyConditionsSchemaApi, zod.null()])
        .optional()
        .describe('Display and targeting conditions for the survey.'),
    appearance: zod
        .union([SurveyAppearanceSchemaApi, zod.null()])
        .optional()
        .describe('Survey appearance customization.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    start_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            "Setting this will launch the survey immediately. Don't add a start_date unless explicitly requested to do so."
        ),
    end_date: zod.iso
        .datetime({ offset: true })
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
        .max(patchedSurveySerializerCreateUpdateOnlySchemaApiIterationCountMax)
        .nullish()
        .describe(
            "For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule."
        ),
    iteration_frequency_days: zod
        .number()
        .min(1)
        .max(patchedSurveySerializerCreateUpdateOnlySchemaApiIterationFrequencyDaysMax)
        .nullish()
        .describe(
            'For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.'
        ),
    iteration_start_dates: zod.array(zod.iso.datetime({ offset: true }).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(patchedSurveySerializerCreateUpdateOnlySchemaApiCurrentIterationMin)
        .max(patchedSurveySerializerCreateUpdateOnlySchemaApiCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_interval_type: zod
        .union([ResponseSamplingIntervalTypeEnumApi, BlankEnumApi, zod.null()])
        .optional(),
    response_sampling_interval: zod
        .number()
        .min(patchedSurveySerializerCreateUpdateOnlySchemaApiResponseSamplingIntervalMin)
        .max(patchedSurveySerializerCreateUpdateOnlySchemaApiResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(patchedSurveySerializerCreateUpdateOnlySchemaApiResponseSamplingLimitMin)
        .max(patchedSurveySerializerCreateUpdateOnlySchemaApiResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().optional(),
    enable_partial_responses: zod
        .boolean()
        .nullish()
        .describe(
            'When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).'
        ),
    enable_iframe_embedding: zod.boolean().nullish(),
    base_language: zod
        .string()
        .max(patchedSurveySerializerCreateUpdateOnlySchemaApiBaseLanguageMax)
        .optional()
        .describe(
            "BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`."
        ),
    translations: zod.unknown().optional(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().optional(),
})

export type PatchedSurveySerializerCreateUpdateOnlySchemaApi = zod.input<
    typeof PatchedSurveySerializerCreateUpdateOnlySchemaApi
>
export type PatchedSurveySerializerCreateUpdateOnlySchemaApiOutput = zod.output<
    typeof PatchedSurveySerializerCreateUpdateOnlySchemaApi
>

export const generateSurveyTranslationsRequestApiOverwriteDefault = false

export const GenerateSurveyTranslationsRequestApi = zod.object({
    target_language: zod.string().describe('Language code to generate translations for, for example pt-BR.'),
    source_language: zod
        .string()
        .optional()
        .describe(
            "Optional override for the source language code. Defaults to the survey's `base_language` (or 'en' if unset)."
        ),
    overwrite: zod
        .boolean()
        .default(generateSurveyTranslationsRequestApiOverwriteDefault)
        .describe('Whether to overwrite existing translations for this language.'),
    survey: zod
        .record(zod.string(), zod.unknown().describe('Draft survey field value.'))
        .optional()
        .describe('Optional translation-only draft survey payload to translate instead of the last saved survey.'),
})

export type GenerateSurveyTranslationsRequestApi = zod.input<typeof GenerateSurveyTranslationsRequestApi>
export type GenerateSurveyTranslationsRequestApiOutput = zod.output<typeof GenerateSurveyTranslationsRequestApi>

export const GeneratedSurveyRootTranslationApi = zod.object({
    name: zod.string().optional().describe('Translated survey name.'),
    thankYouMessageHeader: zod.string().optional().describe('Translated thank-you header.'),
    thankYouMessageDescription: zod.string().optional().describe('Translated thank-you description.'),
    thankYouMessageCloseButtonText: zod.string().optional().describe('Translated thank-you close button text.'),
})

export type GeneratedSurveyRootTranslationApi = zod.input<typeof GeneratedSurveyRootTranslationApi>
export type GeneratedSurveyRootTranslationApiOutput = zod.output<typeof GeneratedSurveyRootTranslationApi>

export const GeneratedSurveyQuestionTranslationApi = zod.object({
    question: zod.string().optional().describe('Translated question text.'),
    description: zod.string().optional().describe('Translated question description.'),
    buttonText: zod.string().optional().describe('Translated submit button text.'),
    choices: zod.array(zod.string()).optional().describe('Translated choices in the same order as the source choices.'),
    lowerBoundLabel: zod.string().optional().describe('Translated lower rating bound label.'),
    upperBoundLabel: zod.string().optional().describe('Translated upper rating bound label.'),
    link: zod.string().optional().describe('Translated link text or localized URL.'),
})

export type GeneratedSurveyQuestionTranslationApi = zod.input<typeof GeneratedSurveyQuestionTranslationApi>
export type GeneratedSurveyQuestionTranslationApiOutput = zod.output<typeof GeneratedSurveyQuestionTranslationApi>

export const GeneratedSurveyQuestionTranslationPatchApi = zod.object({
    id: zod.string().describe('Survey question id this patch applies to.'),
    translations: zod
        .record(zod.string(), GeneratedSurveyQuestionTranslationApi)
        .describe('Question translation patch keyed by target language.'),
})

export type GeneratedSurveyQuestionTranslationPatchApi = zod.input<typeof GeneratedSurveyQuestionTranslationPatchApi>
export type GeneratedSurveyQuestionTranslationPatchApiOutput = zod.output<
    typeof GeneratedSurveyQuestionTranslationPatchApi
>

export const GenerateSurveyTranslationsResponseApi = zod.object({
    translations: zod
        .record(zod.string(), GeneratedSurveyRootTranslationApi)
        .describe('Survey-level translation patch keyed by language.'),
    questions: zod
        .array(GeneratedSurveyQuestionTranslationPatchApi)
        .describe('Question-level translation patches keyed by question id and language.'),
    generated_field_paths: zod
        .array(zod.string())
        .describe('Editor field paths generated by AI and safe to highlight as draft content.'),
    trace_id: zod.string().describe('LLM trace id for debugging and feedback.'),
})

export type GenerateSurveyTranslationsResponseApi = zod.input<typeof GenerateSurveyTranslationsResponseApi>
export type GenerateSurveyTranslationsResponseApiOutput = zod.output<typeof GenerateSurveyTranslationsResponseApi>

export const SurveyResponseAnswerApi = zod.object({
    question_id: zod.string().describe('UUID of the survey question this answer belongs to.'),
    question_index: zod.number().describe('Zero-based index of the question within the survey.'),
    question_text: zod.string().describe('Untranslated question text as configured by the survey author.'),
    question_type: zod
        .string()
        .describe(
            'Question type: open, rating, single_choice, multiple_choice, or link. Determines the shape of the answer field.'
        ),
    answer: zod
        .unknown()
        .describe(
            "Resolved answer. String for open\/rating\/single_choice\/link questions, list of strings for multiple_choice questions. Already decoded from the raw $survey_response_<id> property so callers don't need to parse it."
        ),
})

export type SurveyResponseAnswerApi = zod.input<typeof SurveyResponseAnswerApi>
export type SurveyResponseAnswerApiOutput = zod.output<typeof SurveyResponseAnswerApi>

export const SurveyResponseExtraApi = zod.object({
    device_type: zod.string().nullish().describe('$device_type at the time the response was sent.'),
    browser: zod.string().nullish().describe('$browser at the time the response was sent.'),
    os: zod.string().nullish().describe('$os (operating system) at the time the response was sent.'),
    geoip_country_code: zod.string().nullish().describe('$geoip_country_code at submission time.'),
    geoip_country_name: zod.string().nullish().describe('$geoip_country_name at submission time.'),
    geoip_city_name: zod.string().nullish().describe('$geoip_city_name at submission time.'),
    current_url: zod.string().nullish().describe('$current_url where the survey was submitted.'),
    iteration: zod
        .string()
        .nullish()
        .describe('Survey iteration number when the response was sent. Only set for recurring surveys.'),
})

export type SurveyResponseExtraApi = zod.input<typeof SurveyResponseExtraApi>
export type SurveyResponseExtraApiOutput = zod.output<typeof SurveyResponseExtraApi>

export const SurveyResponseRowApi = zod.object({
    uuid: zod
        .string()
        .describe('UUID of the underlying `survey sent` event. Use as the response identifier for archive operations.'),
    distinct_id: zod
        .string()
        .describe('distinct_id of the respondent. Cross-pivot to the persons API or session recordings.'),
    session_id: zod
        .string()
        .nullable()
        .describe('$session_id of the respondent when available. Use to pull the session recording for this response.'),
    submitted_at: zod.iso
        .datetime({ offset: true })
        .describe('Event timestamp when the response was sent (ISO 8601, UTC).'),
    answers: zod
        .array(SurveyResponseAnswerApi)
        .describe(
            'One entry per survey question that received a non-empty answer. Question text is already resolved — callers do not need to look up `$survey_response_<id>` keys.'
        ),
    extra: SurveyResponseExtraApi.describe(
        'Convenience fields extracted from the event properties (device, browser, geoip, iteration).'
    ),
})

export type SurveyResponseRowApi = zod.input<typeof SurveyResponseRowApi>
export type SurveyResponseRowApiOutput = zod.output<typeof SurveyResponseRowApi>

export const SurveyResponsesListApi = zod.object({
    results: zod.array(SurveyResponseRowApi).describe('Survey response rows for the requested page.'),
    has_more: zod
        .boolean()
        .describe('True if more rows exist beyond the current page — fetch the next page with offset + limit.'),
    limit: zod.number().describe('The limit applied to this query (echoed back for pagination).'),
    offset: zod.number().describe('The offset applied to this query (echoed back for pagination).'),
})

export type SurveyResponsesListApi = zod.input<typeof SurveyResponsesListApi>
export type SurveyResponsesListApiOutput = zod.output<typeof SurveyResponsesListApi>

export const SurveyStatsResponseApi = zod.object({
    survey_id: zod.string().describe('The survey ID these stats belong to.'),
    start_date: zod.iso.datetime({ offset: true }).nullable().describe('When the survey started collecting responses.'),
    end_date: zod.iso.datetime({ offset: true }).nullable().describe('When the survey stopped collecting responses.'),
    stats: zod
        .record(zod.string(), zod.unknown())
        .describe('Event counts keyed by event name (survey shown, survey dismissed, survey sent).'),
    rates: zod.record(zod.string(), zod.unknown()).describe('Calculated response and dismissal rates.'),
    per_question_stats: zod
        .array(zod.unknown())
        .optional()
        .describe(
            'Per-question response counts and distributions. Only present when include_per_question_stats=true was passed. For rating questions includes `average`; for choice\/rating questions `distribution` maps answer value to count; for open questions `distribution` is empty (use surveys-responses-list to read free-text).'
        ),
})

export type SurveyStatsResponseApi = zod.input<typeof SurveyStatsResponseApi>
export type SurveyStatsResponseApiOutput = zod.output<typeof SurveyStatsResponseApi>

export const surveySummarizeRequestApiForceRefreshDefault = false

export const SurveySummarizeRequestApi = zod.object({
    force_refresh: zod
        .boolean()
        .default(surveySummarizeRequestApiForceRefreshDefault)
        .describe('When true, bypass cached summaries and regenerate. Defaults to false.'),
})

export type SurveySummarizeRequestApi = zod.input<typeof SurveySummarizeRequestApi>
export type SurveySummarizeRequestApiOutput = zod.output<typeof SurveySummarizeRequestApi>

export const SurveyQuestionLabelApi = zod.object({
    question_id: zod.string().describe('UUID assigned to the survey question.'),
    question_text: zod.string().describe('Untranslated question text as configured by the survey author.'),
    question_index: zod.number().describe('Zero-based index of the question within the survey.'),
    survey_id: zod.string().describe('UUID of the survey this question belongs to.'),
    survey_name: zod.string().describe('Display name of the survey.'),
})

export type SurveyQuestionLabelApi = zod.input<typeof SurveyQuestionLabelApi>
export type SurveyQuestionLabelApiOutput = zod.output<typeof SurveyQuestionLabelApi>

export const SurveyQuestionLabelsResponseApi = zod.object({
    labels: zod
        .array(SurveyQuestionLabelApi)
        .describe("One entry per question that has an ID assigned, across all the team's surveys."),
})

export type SurveyQuestionLabelsResponseApi = zod.input<typeof SurveyQuestionLabelsResponseApi>
export type SurveyQuestionLabelsResponseApiOutput = zod.output<typeof SurveyQuestionLabelsResponseApi>

export const SurveyGlobalStatsResponseApi = zod.object({
    stats: zod
        .record(zod.string(), zod.unknown())
        .describe('Event counts keyed by event name (survey shown, survey dismissed, survey sent).'),
    rates: zod.record(zod.string(), zod.unknown()).describe('Calculated response and dismissal rates.'),
})

export type SurveyGlobalStatsResponseApi = zod.input<typeof SurveyGlobalStatsResponseApi>
export type SurveyGlobalStatsResponseApiOutput = zod.output<typeof SurveyGlobalStatsResponseApi>
