/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `popover` - popover
 * * `widget` - widget
 * * `external_survey` - external survey
 * * `api` - api
 */
export type SurveyTypeApi = (typeof SurveyTypeApi)[keyof typeof SurveyTypeApi]

export const SurveyTypeApi = {
    Popover: 'popover',
    Widget: 'widget',
    ExternalSurvey: 'external_survey',
    Api: 'api',
} as const

/**
 * * `server` - Server
 * * `client` - Client
 * * `all` - All
 */
export type EvaluationRuntimeEnumApi = (typeof EvaluationRuntimeEnumApi)[keyof typeof EvaluationRuntimeEnumApi]

export const EvaluationRuntimeEnumApi = {
    Server: 'server',
    Client: 'client',
    All: 'all',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * * `distinct_id` - User ID (default)
 * * `device_id` - Device ID
 */
export type BucketingIdentifierEnumApi = (typeof BucketingIdentifierEnumApi)[keyof typeof BucketingIdentifierEnumApi]

export const BucketingIdentifierEnumApi = {
    DistinctId: 'distinct_id',
    DeviceId: 'device_id',
} as const

export type MinimalFeatureFlagApiFilters = { [key: string]: unknown }

export interface MinimalFeatureFlagApi {
    readonly id: number
    readonly team_id: number
    name?: string
    /** @maxLength 400 */
    key: string
    filters?: MinimalFeatureFlagApiFilters
    deleted?: boolean
    active?: boolean
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    version?: number | null
    /** Specifies where this feature flag should be evaluated
     *
     * * `server` - Server
     * * `client` - Client
     * * `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | null
    /** Identifier used for bucketing users into rollout and variants
     *
     * * `distinct_id` - User ID (default)
     * * `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | null
    readonly evaluation_contexts: readonly string[]
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * * `day` - day
 * * `week` - week
 * * `month` - month
 */
export type ResponseSamplingIntervalTypeEnumApi =
    (typeof ResponseSamplingIntervalTypeEnumApi)[keyof typeof ResponseSamplingIntervalTypeEnumApi]

export const ResponseSamplingIntervalTypeEnumApi = {
    Day: 'day',
    Week: 'week',
    Month: 'month',
} as const

export type SearchMatchTypeEnumApi = (typeof SearchMatchTypeEnumApi)[keyof typeof SearchMatchTypeEnumApi]

export const SearchMatchTypeEnumApi = {
    Exact: 'exact',
    Similar: 'similar',
} as const

/**
 * @nullable
 */
export type SurveyApiConditions = { [key: string]: unknown } | null

export type SurveyApiFeatureFlagKeysItem = { [key: string]: string | null }

/**
 * Mixin for serializers to add user access control fields
 */
export interface SurveyApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    description?: string
    type: SurveyTypeApi
    /** @nullable */
    schedule?: string | null
    readonly linked_flag: MinimalFeatureFlagApi
    /** @nullable */
    linked_flag_id?: number | null
    /** @nullable */
    linked_insight_id?: number | null
    readonly targeting_flag: MinimalFeatureFlagApi
    readonly internal_targeting_flag: MinimalFeatureFlagApi
    /**
     *         The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.
     *
     *         Basic (open-ended question)
     *         - `id`: The question ID
     *         - `type`: `open`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Link (a question with a link)
     *         - `id`: The question ID
     *         - `type`: `link`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `link`: The URL associated with the question.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Rating (a question with a rating scale)
     *         - `id`: The question ID
     *         - `type`: `rating`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `display`: Display style of the rating (`number` or `emoji`).
     *         - `scale`: The scale of the rating (`number`).
     *         - `lowerBoundLabel`: Label for the lower bound of the scale.
     *         - `upperBoundLabel`: Label for the upper bound of the scale.
     *         - `isNpsQuestion`: Whether the question is an NPS rating.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Multiple choice
     *         - `id`: The question ID
     *         - `type`: `single_choice` or `multiple_choice`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `choices`: An array of choices for the question.
     *         - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
     *         - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Branching logic can be one of the following types:
     *
     *         Next question: Proceeds to the next question
     *         ```json
     *         {
     *             "type": "next_question"
     *         }
     *         ```
     *
     *         End: Ends the survey, optionally displaying a confirmation message.
     *         ```json
     *         {
     *             "type": "end"
     *         }
     *         ```
     *
     *         Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
     *         ```json
     *         {
     *             "type": "response_based",
     *             "responseValues": {
     *                 "responseKey": "value"
     *             }
     *         }
     *         ```
     *
     *         Specific question: Proceeds to a specific question by index.
     *         ```json
     *         {
     *             "type": "specific_question",
     *             "index": 2
     *         }
     *         ```
     *
     *         Translations: Each question can include inline translations.
     *         - `translations`: Object mapping language codes to translated fields.
     *         - Language codes: Canonical BCP-47-ish strings (e.g., "es", "es-MX", "zh-CN"). Aliases like "english" or "default" are rejected. The survey's `base_language` (default "en") declares the language of the untranslated text and cannot also appear as a translation key.
     *         - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`
     *
     *         Example with translations:
     *         ```json
     *         {
     *             "id": "uuid",
     *             "type": "rating",
     *             "question": "How satisfied are you?",
     *             "lowerBoundLabel": "Not satisfied",
     *             "upperBoundLabel": "Very satisfied",
     *             "translations": {
     *                 "es": {
     *                     "question": "¿Qué tan satisfecho estás?",
     *                     "lowerBoundLabel": "No satisfecho",
     *                     "upperBoundLabel": "Muy satisfecho"
     *                 },
     *                 "fr": {
     *                     "question": "Dans quelle mesure êtes-vous satisfait?"
     *                 }
     *             }
     *         }
     *         ```
     *          */
    questions?: unknown
    /** @nullable */
    readonly conditions: SurveyApiConditions
    appearance?: unknown
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    archived?: boolean
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    responses_limit?: number | null
    readonly feature_flag_keys: readonly SurveyApiFeatureFlagKeysItem[]
    /**
     * @minimum 0
     * @maximum 500
     * @nullable
     */
    iteration_count?: number | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    iteration_frequency_days?: number | null
    /** @nullable */
    iteration_start_dates?: (string | null)[] | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    current_iteration?: number | null
    /** @nullable */
    current_iteration_start_date?: string | null
    /** @nullable */
    response_sampling_start_date?: string | null
    response_sampling_interval_type?: ResponseSamplingIntervalTypeEnumApi | BlankEnumApi | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    response_sampling_interval?: number | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    response_sampling_limit?: number | null
    response_sampling_daily_limits?: unknown
    /** @nullable */
    enable_partial_responses?: boolean | null
    /** @nullable */
    enable_iframe_embedding?: boolean | null
    /**
     * BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`.
     * @maxLength 20
     */
    base_language?: string
    translations?: unknown
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    form_content?: unknown
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. Null when the list is not filtered by `search`. */
    readonly search_match_type: SearchMatchTypeEnumApi | null
}

export interface PaginatedSurveyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SurveyApi[]
}

/**
 * * `once` - once
 * * `recurring` - recurring
 * * `always` - always
 */
export type ScheduleEnumApi = (typeof ScheduleEnumApi)[keyof typeof ScheduleEnumApi]

export const ScheduleEnumApi = {
    Once: 'once',
    Recurring: 'recurring',
    Always: 'always',
} as const

/**
 * * `cohort` - cohort
 * * `person` - person
 * * `group` - group
 */
export type PropertyGroupTypeEnumApi = (typeof PropertyGroupTypeEnumApi)[keyof typeof PropertyGroupTypeEnumApi]

export const PropertyGroupTypeEnumApi = {
    Cohort: 'cohort',
    Person: 'person',
    Group: 'group',
} as const

/**
 * * `exact` - exact
 * * `is_not` - is_not
 * * `icontains` - icontains
 * * `not_icontains` - not_icontains
 * * `regex` - regex
 * * `not_regex` - not_regex
 * * `gt` - gt
 * * `gte` - gte
 * * `lt` - lt
 * * `lte` - lte
 */
export type FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Gte: 'gte',
    Lt: 'lt',
    Lte: 'lte',
} as const

export interface FeatureFlagFilterPropertyGenericSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Comparison value for the property filter. Supports strings, numbers, booleans, and arrays. */
    value: unknown
    /** Operator used to compare the property value.
     *
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `gt` - gt
     * * `gte` - gte
     * * `lt` - lt
     * * `lte` - lte */
    operator: FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi
}

/**
 * * `is_set` - is_set
 * * `is_not_set` - is_not_set
 */
export type ExistenceOperatorEnumApi = (typeof ExistenceOperatorEnumApi)[keyof typeof ExistenceOperatorEnumApi]

export const ExistenceOperatorEnumApi = {
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
} as const

export interface FeatureFlagFilterPropertyExistsSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Existence operator.
     *
     * * `is_set` - is_set
     * * `is_not_set` - is_not_set */
    operator: ExistenceOperatorEnumApi
    /** Optional value. Runtime behavior determines whether this is ignored. */
    value?: unknown
}

/**
 * * `is_date_exact` - is_date_exact
 * * `is_date_before` - is_date_before
 * * `is_date_after` - is_date_after
 */
export type DateOperatorEnumApi = (typeof DateOperatorEnumApi)[keyof typeof DateOperatorEnumApi]

export const DateOperatorEnumApi = {
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
} as const

export interface FeatureFlagFilterPropertyDateSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Date comparison operator.
     *
     * * `is_date_exact` - is_date_exact
     * * `is_date_after` - is_date_after
     * * `is_date_before` - is_date_before */
    operator: DateOperatorEnumApi
    /** Date value in ISO format or relative date expression. */
    value: string
}

/**
 * * `semver_gt` - semver_gt
 * * `semver_gte` - semver_gte
 * * `semver_lt` - semver_lt
 * * `semver_lte` - semver_lte
 * * `semver_eq` - semver_eq
 * * `semver_neq` - semver_neq
 * * `semver_tilde` - semver_tilde
 * * `semver_caret` - semver_caret
 * * `semver_wildcard` - semver_wildcard
 */
export type FeatureFlagFilterPropertySemverSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertySemverSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertySemverSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertySemverSchemaOperatorEnumApi = {
    SemverGt: 'semver_gt',
    SemverGte: 'semver_gte',
    SemverLt: 'semver_lt',
    SemverLte: 'semver_lte',
    SemverEq: 'semver_eq',
    SemverNeq: 'semver_neq',
    SemverTilde: 'semver_tilde',
    SemverCaret: 'semver_caret',
    SemverWildcard: 'semver_wildcard',
} as const

export interface FeatureFlagFilterPropertySemverSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Semantic version comparison operator.
     *
     * * `semver_gt` - semver_gt
     * * `semver_gte` - semver_gte
     * * `semver_lt` - semver_lt
     * * `semver_lte` - semver_lte
     * * `semver_eq` - semver_eq
     * * `semver_neq` - semver_neq
     * * `semver_tilde` - semver_tilde
     * * `semver_caret` - semver_caret
     * * `semver_wildcard` - semver_wildcard */
    operator: FeatureFlagFilterPropertySemverSchemaOperatorEnumApi
    /** Semantic version string. */
    value: string
}

/**
 * * `icontains_multi` - icontains_multi
 * * `not_icontains_multi` - not_icontains_multi
 */
export type FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi = {
    IcontainsMulti: 'icontains_multi',
    NotIcontainsMulti: 'not_icontains_multi',
} as const

export interface FeatureFlagFilterPropertyMultiContainsSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Multi-contains operator.
     *
     * * `icontains_multi` - icontains_multi
     * * `not_icontains_multi` - not_icontains_multi */
    operator: FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi
    /** List of strings to evaluate against. */
    value: string[]
}

/**
 * * `cohort` - cohort
 */
export type FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi =
    (typeof FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi)[keyof typeof FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi]

export const FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi = {
    Cohort: 'cohort',
} as const

/**
 * * `in` - in
 * * `not_in` - not_in
 */
export type FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi = {
    In: 'in',
    NotIn: 'not_in',
} as const

export interface FeatureFlagFilterPropertyCohortInSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Cohort property type required for in/not_in operators.
     *
     * * `cohort` - cohort */
    type: FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Membership operator for cohort properties.
     *
     * * `in` - in
     * * `not_in` - not_in */
    operator: FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi
    /** Cohort comparison value (single or list, depending on usage). */
    value: unknown
}

/**
 * * `flag` - flag
 */
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi =
    (typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi)[keyof typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi]

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi = {
    Flag: 'flag',
} as const

/**
 * * `flag_evaluates_to` - flag_evaluates_to
 */
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi = {
    FlagEvaluatesTo: 'flag_evaluates_to',
} as const

export interface FeatureFlagFilterPropertyFlagEvaluatesSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Flag property type required for flag dependency checks.
     *
     * * `flag` - flag */
    type: FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Operator for feature flag dependency evaluation.
     *
     * * `flag_evaluates_to` - flag_evaluates_to */
    operator: FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi
    /** Value to compare flag evaluation against. */
    value: unknown
}

export type FeatureFlagFilterPropertySchemaApi =
    | FeatureFlagFilterPropertyGenericSchemaApi
    | FeatureFlagFilterPropertyExistsSchemaApi
    | FeatureFlagFilterPropertyDateSchemaApi
    | FeatureFlagFilterPropertySemverSchemaApi
    | FeatureFlagFilterPropertyMultiContainsSchemaApi
    | FeatureFlagFilterPropertyCohortInSchemaApi
    | FeatureFlagFilterPropertyFlagEvaluatesSchemaApi

export interface FeatureFlagConditionGroupSchemaApi {
    /** Property conditions for this release condition group. */
    properties?: FeatureFlagFilterPropertySchemaApi[]
    /** Rollout percentage for this release condition group. */
    rollout_percentage?: number
    /**
     * Variant key override for multivariate flags.
     * @nullable
     */
    variant?: string | null
    /**
     * Group type index for this condition set. None means person-level aggregation.
     * @nullable
     */
    aggregation_group_type_index?: number | null
}

export interface FeatureFlagMultivariateVariantSchemaApi {
    /** Unique key for this variant. */
    key: string
    /** Human-readable name for this variant. */
    name?: string
    /** Variant rollout percentage. */
    rollout_percentage: number
}

export interface FeatureFlagMultivariateSchemaApi {
    /** Variant definitions for multivariate feature flags. */
    variants: FeatureFlagMultivariateVariantSchemaApi[]
}

/**
 * Optional payload values keyed by variant key.
 */
export type FeatureFlagFiltersSchemaApiPayloads = { [key: string]: string }

export interface FeatureFlagFiltersSchemaApi {
    /** Release condition groups for the feature flag. */
    groups?: FeatureFlagConditionGroupSchemaApi[]
    /** Multivariate configuration for variant-based rollouts. */
    multivariate?: FeatureFlagMultivariateSchemaApi | null
    /**
     * Group type index for group-based feature flags.
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Optional payload values keyed by variant key. */
    payloads?: FeatureFlagFiltersSchemaApiPayloads
    /**
     * Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment/{flag_key}.
     * @nullable
     */
    feature_enrollment?: boolean | null
    /** When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups. */
    early_exit?: boolean
}

/**
 * * `open` - open
 */
export type SurveyOpenQuestionSchemaTypeEnumApi =
    (typeof SurveyOpenQuestionSchemaTypeEnumApi)[keyof typeof SurveyOpenQuestionSchemaTypeEnumApi]

export const SurveyOpenQuestionSchemaTypeEnumApi = {
    Open: 'open',
} as const

/**
 * * `html` - html
 * * `text` - text
 */
export type DescriptionContentTypeEnumApi =
    (typeof DescriptionContentTypeEnumApi)[keyof typeof DescriptionContentTypeEnumApi]

export const DescriptionContentTypeEnumApi = {
    Html: 'html',
    Text: 'text',
} as const

export interface SurveyOpenQuestionSchemaApi {
    /** Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one. */
    id?: string
    type: SurveyOpenQuestionSchemaTypeEnumApi
    /** Question text shown to respondents. */
    question: string
    /** Optional helper text. */
    description?: string
    /** Format for the description field.
     *
     * * `text` - text
     * * `html` - html */
    descriptionContentType?: DescriptionContentTypeEnumApi
    /** Whether respondents may skip this question. */
    optional?: boolean
    /** Custom button label. */
    buttonText?: string
}

/**
 * * `link` - link
 */
export type SurveyLinkQuestionSchemaTypeEnumApi =
    (typeof SurveyLinkQuestionSchemaTypeEnumApi)[keyof typeof SurveyLinkQuestionSchemaTypeEnumApi]

export const SurveyLinkQuestionSchemaTypeEnumApi = {
    Link: 'link',
} as const

export interface SurveyLinkQuestionSchemaApi {
    /** Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one. */
    id?: string
    type: SurveyLinkQuestionSchemaTypeEnumApi
    /** Question text shown to respondents. */
    question: string
    /** Optional helper text. */
    description?: string
    /** Format for the description field.
     *
     * * `text` - text
     * * `html` - html */
    descriptionContentType?: DescriptionContentTypeEnumApi
    /** Whether respondents may skip this question. */
    optional?: boolean
    /** Custom button label. */
    buttonText?: string
    /** HTTPS or mailto URL for link questions. */
    link: string
}

/**
 * * `rating` - rating
 */
export type SurveyRatingQuestionSchemaTypeEnumApi =
    (typeof SurveyRatingQuestionSchemaTypeEnumApi)[keyof typeof SurveyRatingQuestionSchemaTypeEnumApi]

export const SurveyRatingQuestionSchemaTypeEnumApi = {
    Rating: 'rating',
} as const

/**
 * * `number` - number
 * * `emoji` - emoji
 */
export type SurveyRatingQuestionSchemaDisplayEnumApi =
    (typeof SurveyRatingQuestionSchemaDisplayEnumApi)[keyof typeof SurveyRatingQuestionSchemaDisplayEnumApi]

export const SurveyRatingQuestionSchemaDisplayEnumApi = {
    Number: 'number',
    Emoji: 'emoji',
} as const

/**
 * * `next_question` - next_question
 */
export type SurveyNextQuestionBranchingTypeEnumApi =
    (typeof SurveyNextQuestionBranchingTypeEnumApi)[keyof typeof SurveyNextQuestionBranchingTypeEnumApi]

export const SurveyNextQuestionBranchingTypeEnumApi = {
    NextQuestion: 'next_question',
} as const

export interface SurveyNextQuestionBranchingApi {
    /** Continue to the next question in sequence.
     *
     * * `next_question` - next_question */
    type: SurveyNextQuestionBranchingTypeEnumApi
}

/**
 * * `end` - end
 */
export type SurveyEndBranchingTypeEnumApi =
    (typeof SurveyEndBranchingTypeEnumApi)[keyof typeof SurveyEndBranchingTypeEnumApi]

export const SurveyEndBranchingTypeEnumApi = {
    End: 'end',
} as const

export interface SurveyEndBranchingApi {
    /** End the survey.
     *
     * * `end` - end */
    type: SurveyEndBranchingTypeEnumApi
}

/**
 * * `specific_question` - specific_question
 */
export type SurveySpecificQuestionBranchingTypeEnumApi =
    (typeof SurveySpecificQuestionBranchingTypeEnumApi)[keyof typeof SurveySpecificQuestionBranchingTypeEnumApi]

export const SurveySpecificQuestionBranchingTypeEnumApi = {
    SpecificQuestion: 'specific_question',
} as const

export interface SurveySpecificQuestionBranchingApi {
    /** Jump to a specific question index.
     *
     * * `specific_question` - specific_question */
    type: SurveySpecificQuestionBranchingTypeEnumApi
    /**
     * 0-based index of the next question.
     * @minimum 0
     */
    index: number
}

/**
 * * `response_based` - response_based
 */
export type SurveyResponseBasedBranchingTypeEnumApi =
    (typeof SurveyResponseBasedBranchingTypeEnumApi)[keyof typeof SurveyResponseBasedBranchingTypeEnumApi]

export const SurveyResponseBasedBranchingTypeEnumApi = {
    ResponseBased: 'response_based',
} as const

/**
 * Response-based branching map. Values can be a question index or 'end'.
 */
export type SurveyResponseBasedBranchingApiResponseValues = { [key: string]: number | 'end' }

export interface SurveyResponseBasedBranchingApi {
    /** Branch based on the selected or entered response.
     *
     * * `response_based` - response_based */
    type: SurveyResponseBasedBranchingTypeEnumApi
    /** Response-based branching map. Values can be a question index or 'end'. */
    responseValues: SurveyResponseBasedBranchingApiResponseValues
}

export type SurveyBranchingSchemaApi =
    | SurveyNextQuestionBranchingApi
    | SurveyEndBranchingApi
    | SurveySpecificQuestionBranchingApi
    | SurveyResponseBasedBranchingApi

export interface SurveyRatingQuestionSchemaApi {
    /** Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one. */
    id?: string
    type: SurveyRatingQuestionSchemaTypeEnumApi
    /** Question text shown to respondents. */
    question: string
    /** Optional helper text. */
    description?: string
    /** Format for the description field.
     *
     * * `text` - text
     * * `html` - html */
    descriptionContentType?: DescriptionContentTypeEnumApi
    /** Whether respondents may skip this question. */
    optional?: boolean
    /** Custom button label. */
    buttonText?: string
    /** Display format: 'number' shows numeric scale, 'emoji' shows emoji scale.
     *
     * * `number` - number
     * * `emoji` - emoji */
    display?: SurveyRatingQuestionSchemaDisplayEnumApi
    /**
     * Rating scale can be one of 3, 5, or 7
     * @minimum 1
     */
    scale?: number
    /** Label for the lowest rating (e.g., 'Very Poor') */
    lowerBoundLabel?: string
    /** Label for the highest rating (e.g., 'Excellent') */
    upperBoundLabel?: string
    branching?: SurveyBranchingSchemaApi | null
}

/**
 * * `single_choice` - single_choice
 */
export type SurveySingleChoiceQuestionSchemaTypeEnumApi =
    (typeof SurveySingleChoiceQuestionSchemaTypeEnumApi)[keyof typeof SurveySingleChoiceQuestionSchemaTypeEnumApi]

export const SurveySingleChoiceQuestionSchemaTypeEnumApi = {
    SingleChoice: 'single_choice',
} as const

export interface SurveySingleChoiceQuestionSchemaApi {
    /** Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one. */
    id?: string
    type: SurveySingleChoiceQuestionSchemaTypeEnumApi
    /** Question text shown to respondents. */
    question: string
    /** Optional helper text. */
    description?: string
    /** Format for the description field.
     *
     * * `text` - text
     * * `html` - html */
    descriptionContentType?: DescriptionContentTypeEnumApi
    /** Whether respondents may skip this question. */
    optional?: boolean
    /** Custom button label. */
    buttonText?: string
    /**
     * Array of choice options. Choice indices (0, 1, 2, ...) are used for branching logic.
     * @minItems 2
     * @maxItems 20
     */
    choices: string[]
    /** Whether to randomize the order of choices for each respondent. */
    shuffleOptions?: boolean
    /** Whether the final option should be an open-text choice (for example, 'Other'). */
    hasOpenChoice?: boolean
    branching?: SurveyBranchingSchemaApi | null
}

/**
 * * `multiple_choice` - multiple_choice
 */
export type SurveyMultipleChoiceQuestionSchemaTypeEnumApi =
    (typeof SurveyMultipleChoiceQuestionSchemaTypeEnumApi)[keyof typeof SurveyMultipleChoiceQuestionSchemaTypeEnumApi]

export const SurveyMultipleChoiceQuestionSchemaTypeEnumApi = {
    MultipleChoice: 'multiple_choice',
} as const

export interface SurveyMultipleChoiceQuestionSchemaApi {
    /** Stable question identifier (UUID). When editing an existing question, send back its current id so its responses (keyed by $survey_response_<id>) stay attached; omit it for new questions and the server generates one. */
    id?: string
    type: SurveyMultipleChoiceQuestionSchemaTypeEnumApi
    /** Question text shown to respondents. */
    question: string
    /** Optional helper text. */
    description?: string
    /** Format for the description field.
     *
     * * `text` - text
     * * `html` - html */
    descriptionContentType?: DescriptionContentTypeEnumApi
    /** Whether respondents may skip this question. */
    optional?: boolean
    /** Custom button label. */
    buttonText?: string
    /**
     * Array of choice options. Multiple selections allowed. No branching logic supported.
     * @minItems 2
     * @maxItems 20
     */
    choices: string[]
    /** Whether to randomize the order of choices for each respondent. */
    shuffleOptions?: boolean
    /** Whether the final option should be an open-text choice (for example, 'Other'). */
    hasOpenChoice?: boolean
}

export type SurveyQuestionInputSchemaApi =
    | SurveyOpenQuestionSchemaApi
    | SurveyLinkQuestionSchemaApi
    | SurveyRatingQuestionSchemaApi
    | SurveySingleChoiceQuestionSchemaApi
    | SurveyMultipleChoiceQuestionSchemaApi

/**
 * * `exact` - exact
 * * `is_not` - is_not
 * * `icontains` - icontains
 * * `not_icontains` - not_icontains
 * * `regex` - regex
 * * `not_regex` - not_regex
 */
export type StringMatchOperatorEnumApi = (typeof StringMatchOperatorEnumApi)[keyof typeof StringMatchOperatorEnumApi]

export const StringMatchOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
} as const

export interface SurveyConditionEventValueSchemaApi {
    /** Event name that triggers the survey. */
    name: string
}

export interface SurveyEventsConditionSchemaApi {
    /** Whether to show the survey every time one of the events is triggered (true), or just once (false). */
    repeatedActivation?: boolean
    /** Array of event names that trigger the survey. */
    values?: SurveyConditionEventValueSchemaApi[]
}

/**
 * * `Desktop` - Desktop
 * * `Mobile` - Mobile
 * * `Tablet` - Tablet
 */
export type DeviceTypesEnumApi = (typeof DeviceTypesEnumApi)[keyof typeof DeviceTypesEnumApi]

export const DeviceTypesEnumApi = {
    Desktop: 'Desktop',
    Mobile: 'Mobile',
    Tablet: 'Tablet',
} as const

export interface SurveyConditionsSchemaApi {
    url?: string
    selector?: string
    /**
     * Don't show this survey to users who saw any survey in the last x days.
     * @minimum 0
     */
    seenSurveyWaitPeriodInDays?: number
    /** URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain).
     *
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains */
    urlMatchType?: StringMatchOperatorEnumApi
    events?: SurveyEventsConditionSchemaApi
    /** Device types that should match for this survey to be shown. */
    deviceTypes?: DeviceTypesEnumApi[]
    /** URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain).
     *
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains */
    deviceTypesMatchType?: StringMatchOperatorEnumApi
    /** The variant of the feature flag linked to this survey. */
    linkedFlagVariant?: string
}

/**
 * * `button` - button
 * * `tab` - tab
 * * `selector` - selector
 */
export type WidgetTypeEnumApi = (typeof WidgetTypeEnumApi)[keyof typeof WidgetTypeEnumApi]

export const WidgetTypeEnumApi = {
    Button: 'button',
    Tab: 'tab',
    Selector: 'selector',
} as const

export interface SurveyAppearanceSchemaApi {
    backgroundColor?: string
    submitButtonColor?: string
    textColor?: string
    submitButtonText?: string
    submitButtonTextColor?: string
    descriptionTextColor?: string
    ratingButtonColor?: string
    ratingButtonActiveColor?: string
    ratingButtonHoverColor?: string
    whiteLabel?: boolean
    autoDisappear?: boolean
    displayThankYouMessage?: boolean
    thankYouMessageHeader?: string
    thankYouMessageDescription?: string
    thankYouMessageDescriptionContentType?: DescriptionContentTypeEnumApi
    thankYouMessageCloseButtonText?: string
    borderColor?: string
    placeholder?: string
    shuffleQuestions?: boolean
    surveyPopupDelaySeconds?: number
    /** Whether to show a 'Back' button on web surveys after the first question, letting respondents return to a previously visited question. Defaults to false. */
    allowGoBack?: boolean
    /** Optional override for the back button label. Defaults to 'Back'. */
    backButtonText?: string
    widgetType?: WidgetTypeEnumApi
    widgetSelector?: string
    widgetLabel?: string
    widgetColor?: string
    fontFamily?: string
    maxWidth?: string
    zIndex?: string
    disabledButtonOpacity?: string
    boxPadding?: string
}

export interface SurveySerializerCreateUpdateOnlySchemaApi {
    readonly id: string
    /**
     * Survey name.
     * @minLength 1
     * @maxLength 400
     */
    name: string
    /** Survey description. */
    description?: string
    /** Survey type.
     *
     * * `popover` - popover
     * * `widget` - widget
     * * `external_survey` - external survey
     * * `api` - api */
    type: SurveyTypeApi
    /** Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)
     *
     * * `once` - once
     * * `recurring` - recurring
     * * `always` - always */
    schedule?: ScheduleEnumApi | null
    readonly linked_flag: MinimalFeatureFlagApi
    /**
     * The feature flag linked to this survey.
     * @nullable
     */
    linked_flag_id?: number | null
    /** @nullable */
    linked_insight_id?: number | null
    /** An existing targeting flag to use for this survey. */
    targeting_flag_id?: number
    readonly targeting_flag: MinimalFeatureFlagApi
    readonly internal_targeting_flag: MinimalFeatureFlagApi
    /** Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 100}]} */
    targeting_flag_filters?: FeatureFlagFiltersSchemaApi | null
    /**
     * Set to true to completely remove all targeting filters from the survey, making it visible to all users (subject to other display conditions like URL matching).
     * @nullable
     */
    remove_targeting_flag?: boolean | null
    /**
     *
     *         The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.
     *
     *         Basic (open-ended question)
     *         - `id`: The question ID
     *         - `type`: `open`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Link (a question with a link)
     *         - `id`: The question ID
     *         - `type`: `link`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `link`: The URL associated with the question.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Rating (a question with a rating scale)
     *         - `id`: The question ID
     *         - `type`: `rating`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `display`: Display style of the rating (`number` or `emoji`).
     *         - `scale`: The scale of the rating (`number`).
     *         - `lowerBoundLabel`: Label for the lower bound of the scale.
     *         - `upperBoundLabel`: Label for the upper bound of the scale.
     *         - `isNpsQuestion`: Whether the question is an NPS rating.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Multiple choice
     *         - `id`: The question ID
     *         - `type`: `single_choice` or `multiple_choice`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `choices`: An array of choices for the question.
     *         - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
     *         - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Branching logic can be one of the following types:
     *
     *         Next question: Proceeds to the next question
     *         ```json
     *         {
     *             "type": "next_question"
     *         }
     *         ```
     *
     *         End: Ends the survey, optionally displaying a confirmation message.
     *         ```json
     *         {
     *             "type": "end"
     *         }
     *         ```
     *
     *         Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
     *         ```json
     *         {
     *             "type": "response_based",
     *             "responseValues": {
     *                 "responseKey": "value"
     *             }
     *         }
     *         ```
     *
     *         Specific question: Proceeds to a specific question by index.
     *         ```json
     *         {
     *             "type": "specific_question",
     *             "index": 2
     *         }
     *         ```
     *
     *         Translations: Each question can include inline translations.
     *         - `translations`: Object mapping language codes to translated fields.
     *         - Language codes: Canonical BCP-47-ish strings (e.g., "es", "es-MX", "zh-CN"). Aliases like "english" or "default" are rejected. The survey's `base_language` (default "en") declares the language of the untranslated text and cannot also appear as a translation key.
     *         - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`
     *
     *         Example with translations:
     *         ```json
     *         {
     *             "id": "uuid",
     *             "type": "rating",
     *             "question": "How satisfied are you?",
     *             "lowerBoundLabel": "Not satisfied",
     *             "upperBoundLabel": "Very satisfied",
     *             "translations": {
     *                 "es": {
     *                     "question": "¿Qué tan satisfecho estás?",
     *                     "lowerBoundLabel": "No satisfecho",
     *                     "upperBoundLabel": "Muy satisfecho"
     *                 },
     *                 "fr": {
     *                     "question": "Dans quelle mesure êtes-vous satisfait?"
     *                 }
     *             }
     *         }
     *         ```
     *
     * @nullable
     */
    questions?: SurveyQuestionInputSchemaApi[] | null
    /** Display and targeting conditions for the survey. */
    conditions?: SurveyConditionsSchemaApi | null
    /** Survey appearance customization. */
    appearance?: SurveyAppearanceSchemaApi | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    /**
     * Setting this will launch the survey immediately. Don't add a start_date unless explicitly requested to do so.
     * @nullable
     */
    start_date?: string | null
    /**
     * When the survey stopped being shown to users. Setting this will complete the survey.
     * @nullable
     */
    end_date?: string | null
    /** Archive state for the survey. */
    archived?: boolean
    /**
     * Cumulative lifetime response target. When total unique responses (counted since the survey started, across all iterations) reach this number, an hourly task stops the survey and clears this field. This is a running total, not a per-iteration or monthly quota: raising it on a survey that already has responses reopens the survey only until the new total is reached, and setting a value below the existing total stops it on the next hourly tick.
     * @nullable
     */
    responses_limit?: number | null
    /**
     * For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule.
     * @minimum 1
     * @maximum 500
     * @nullable
     */
    iteration_count?: number | null
    /**
     * For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.
     * @minimum 1
     * @maximum 365
     * @nullable
     */
    iteration_frequency_days?: number | null
    /** @nullable */
    iteration_start_dates?: (string | null)[] | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    current_iteration?: number | null
    /** @nullable */
    current_iteration_start_date?: string | null
    /** @nullable */
    response_sampling_start_date?: string | null
    response_sampling_interval_type?: ResponseSamplingIntervalTypeEnumApi | BlankEnumApi | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    response_sampling_interval?: number | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    response_sampling_limit?: number | null
    response_sampling_daily_limits?: unknown
    /**
     * When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).
     * @nullable
     */
    enable_partial_responses?: boolean | null
    /** @nullable */
    enable_iframe_embedding?: boolean | null
    /**
     * BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`.
     * @maxLength 20
     */
    base_language?: string
    translations?: unknown
    _create_in_folder?: string
    form_content?: unknown
}

export interface SurveySerializerCreateUpdateOnlyApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    description?: string
    type: SurveyTypeApi
    /** @nullable */
    schedule?: string | null
    readonly linked_flag: MinimalFeatureFlagApi
    /** @nullable */
    linked_flag_id?: number | null
    /** @nullable */
    linked_insight_id?: number | null
    targeting_flag_id?: number
    readonly targeting_flag: MinimalFeatureFlagApi
    readonly internal_targeting_flag: MinimalFeatureFlagApi
    targeting_flag_filters?: unknown
    /** @nullable */
    remove_targeting_flag?: boolean | null
    /**
     *         The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.
     *
     *         Basic (open-ended question)
     *         - `id`: The question ID
     *         - `type`: `open`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Link (a question with a link)
     *         - `id`: The question ID
     *         - `type`: `link`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `link`: The URL associated with the question.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Rating (a question with a rating scale)
     *         - `id`: The question ID
     *         - `type`: `rating`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `display`: Display style of the rating (`number` or `emoji`).
     *         - `scale`: The scale of the rating (`number`).
     *         - `lowerBoundLabel`: Label for the lower bound of the scale.
     *         - `upperBoundLabel`: Label for the upper bound of the scale.
     *         - `isNpsQuestion`: Whether the question is an NPS rating.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Multiple choice
     *         - `id`: The question ID
     *         - `type`: `single_choice` or `multiple_choice`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `choices`: An array of choices for the question.
     *         - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
     *         - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Branching logic can be one of the following types:
     *
     *         Next question: Proceeds to the next question
     *         ```json
     *         {
     *             "type": "next_question"
     *         }
     *         ```
     *
     *         End: Ends the survey, optionally displaying a confirmation message.
     *         ```json
     *         {
     *             "type": "end"
     *         }
     *         ```
     *
     *         Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
     *         ```json
     *         {
     *             "type": "response_based",
     *             "responseValues": {
     *                 "responseKey": "value"
     *             }
     *         }
     *         ```
     *
     *         Specific question: Proceeds to a specific question by index.
     *         ```json
     *         {
     *             "type": "specific_question",
     *             "index": 2
     *         }
     *         ```
     *
     *         Translations: Each question can include inline translations.
     *         - `translations`: Object mapping language codes to translated fields.
     *         - Language codes: Canonical BCP-47-ish strings (e.g., "es", "es-MX", "zh-CN"). Aliases like "english" or "default" are rejected. The survey's `base_language` (default "en") declares the language of the untranslated text and cannot also appear as a translation key.
     *         - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`
     *
     *         Example with translations:
     *         ```json
     *         {
     *             "id": "uuid",
     *             "type": "rating",
     *             "question": "How satisfied are you?",
     *             "lowerBoundLabel": "Not satisfied",
     *             "upperBoundLabel": "Very satisfied",
     *             "translations": {
     *                 "es": {
     *                     "question": "¿Qué tan satisfecho estás?",
     *                     "lowerBoundLabel": "No satisfecho",
     *                     "upperBoundLabel": "Muy satisfecho"
     *                 },
     *                 "fr": {
     *                     "question": "Dans quelle mesure êtes-vous satisfait?"
     *                 }
     *             }
     *         }
     *         ```
     *          */
    questions?: unknown
    conditions?: unknown
    appearance?: unknown
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    archived?: boolean
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    responses_limit?: number | null
    /**
     * @minimum 0
     * @maximum 500
     * @nullable
     */
    iteration_count?: number | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    iteration_frequency_days?: number | null
    /** @nullable */
    iteration_start_dates?: (string | null)[] | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    current_iteration?: number | null
    /** @nullable */
    current_iteration_start_date?: string | null
    /** @nullable */
    response_sampling_start_date?: string | null
    response_sampling_interval_type?: ResponseSamplingIntervalTypeEnumApi | BlankEnumApi | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    response_sampling_interval?: number | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    response_sampling_limit?: number | null
    response_sampling_daily_limits?: unknown
    /** @nullable */
    enable_partial_responses?: boolean | null
    /** @nullable */
    enable_iframe_embedding?: boolean | null
    /**
     * BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`.
     * @maxLength 20
     */
    base_language?: string
    translations?: unknown
    _create_in_folder?: string
    form_content?: unknown
}

export interface PatchedSurveySerializerCreateUpdateOnlySchemaApi {
    readonly id?: string
    /**
     * Survey name.
     * @minLength 1
     * @maxLength 400
     */
    name?: string
    /** Survey description. */
    description?: string
    /** Survey type.
     *
     * * `popover` - popover
     * * `widget` - widget
     * * `external_survey` - external survey
     * * `api` - api */
    type?: SurveyTypeApi
    /** Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)
     *
     * * `once` - once
     * * `recurring` - recurring
     * * `always` - always */
    schedule?: ScheduleEnumApi | null
    readonly linked_flag?: MinimalFeatureFlagApi
    /**
     * The feature flag linked to this survey.
     * @nullable
     */
    linked_flag_id?: number | null
    /** @nullable */
    linked_insight_id?: number | null
    /** An existing targeting flag to use for this survey. */
    targeting_flag_id?: number
    readonly targeting_flag?: MinimalFeatureFlagApi
    readonly internal_targeting_flag?: MinimalFeatureFlagApi
    /** Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 100}]} */
    targeting_flag_filters?: FeatureFlagFiltersSchemaApi | null
    /**
     * Set to true to completely remove all targeting filters from the survey, making it visible to all users (subject to other display conditions like URL matching).
     * @nullable
     */
    remove_targeting_flag?: boolean | null
    /**
     *
     *         The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.
     *
     *         Basic (open-ended question)
     *         - `id`: The question ID
     *         - `type`: `open`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Link (a question with a link)
     *         - `id`: The question ID
     *         - `type`: `link`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `link`: The URL associated with the question.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Rating (a question with a rating scale)
     *         - `id`: The question ID
     *         - `type`: `rating`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `display`: Display style of the rating (`number` or `emoji`).
     *         - `scale`: The scale of the rating (`number`).
     *         - `lowerBoundLabel`: Label for the lower bound of the scale.
     *         - `upperBoundLabel`: Label for the upper bound of the scale.
     *         - `isNpsQuestion`: Whether the question is an NPS rating.
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Multiple choice
     *         - `id`: The question ID
     *         - `type`: `single_choice` or `multiple_choice`
     *         - `question`: The text of the question.
     *         - `description`: Optional description of the question.
     *         - `descriptionContentType`: Content type of the description (`html` or `text`).
     *         - `optional`: Whether the question is optional (`boolean`).
     *         - `buttonText`: Text displayed on the submit button.
     *         - `choices`: An array of choices for the question.
     *         - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
     *         - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
     *         - `branching`: Branching logic for the question. See branching types below for details.
     *
     *         Branching logic can be one of the following types:
     *
     *         Next question: Proceeds to the next question
     *         ```json
     *         {
     *             "type": "next_question"
     *         }
     *         ```
     *
     *         End: Ends the survey, optionally displaying a confirmation message.
     *         ```json
     *         {
     *             "type": "end"
     *         }
     *         ```
     *
     *         Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
     *         ```json
     *         {
     *             "type": "response_based",
     *             "responseValues": {
     *                 "responseKey": "value"
     *             }
     *         }
     *         ```
     *
     *         Specific question: Proceeds to a specific question by index.
     *         ```json
     *         {
     *             "type": "specific_question",
     *             "index": 2
     *         }
     *         ```
     *
     *         Translations: Each question can include inline translations.
     *         - `translations`: Object mapping language codes to translated fields.
     *         - Language codes: Canonical BCP-47-ish strings (e.g., "es", "es-MX", "zh-CN"). Aliases like "english" or "default" are rejected. The survey's `base_language` (default "en") declares the language of the untranslated text and cannot also appear as a translation key.
     *         - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`
     *
     *         Example with translations:
     *         ```json
     *         {
     *             "id": "uuid",
     *             "type": "rating",
     *             "question": "How satisfied are you?",
     *             "lowerBoundLabel": "Not satisfied",
     *             "upperBoundLabel": "Very satisfied",
     *             "translations": {
     *                 "es": {
     *                     "question": "¿Qué tan satisfecho estás?",
     *                     "lowerBoundLabel": "No satisfecho",
     *                     "upperBoundLabel": "Muy satisfecho"
     *                 },
     *                 "fr": {
     *                     "question": "Dans quelle mesure êtes-vous satisfait?"
     *                 }
     *             }
     *         }
     *         ```
     *
     * @nullable
     */
    questions?: SurveyQuestionInputSchemaApi[] | null
    /** Display and targeting conditions for the survey. */
    conditions?: SurveyConditionsSchemaApi | null
    /** Survey appearance customization. */
    appearance?: SurveyAppearanceSchemaApi | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /**
     * Setting this will launch the survey immediately. Don't add a start_date unless explicitly requested to do so.
     * @nullable
     */
    start_date?: string | null
    /**
     * When the survey stopped being shown to users. Setting this will complete the survey.
     * @nullable
     */
    end_date?: string | null
    /** Archive state for the survey. */
    archived?: boolean
    /**
     * Cumulative lifetime response target. When total unique responses (counted since the survey started, across all iterations) reach this number, an hourly task stops the survey and clears this field. This is a running total, not a per-iteration or monthly quota: raising it on a survey that already has responses reopens the survey only until the new total is reached, and setting a value below the existing total stops it on the next hourly tick.
     * @nullable
     */
    responses_limit?: number | null
    /**
     * For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule.
     * @minimum 1
     * @maximum 500
     * @nullable
     */
    iteration_count?: number | null
    /**
     * For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.
     * @minimum 1
     * @maximum 365
     * @nullable
     */
    iteration_frequency_days?: number | null
    /** @nullable */
    iteration_start_dates?: (string | null)[] | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    current_iteration?: number | null
    /** @nullable */
    current_iteration_start_date?: string | null
    /** @nullable */
    response_sampling_start_date?: string | null
    response_sampling_interval_type?: ResponseSamplingIntervalTypeEnumApi | BlankEnumApi | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    response_sampling_interval?: number | null
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    response_sampling_limit?: number | null
    response_sampling_daily_limits?: unknown
    /**
     * When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).
     * @nullable
     */
    enable_partial_responses?: boolean | null
    /** @nullable */
    enable_iframe_embedding?: boolean | null
    /**
     * BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`.
     * @maxLength 20
     */
    base_language?: string
    translations?: unknown
    _create_in_folder?: string
    form_content?: unknown
}

/**
 * Optional translation-only draft survey payload to translate instead of the last saved survey.
 */
export type GenerateSurveyTranslationsRequestApiSurvey = { [key: string]: unknown }

export interface GenerateSurveyTranslationsRequestApi {
    /** Language code to generate translations for, for example pt-BR. */
    target_language: string
    /** Optional override for the source language code. Defaults to the survey's `base_language` (or 'en' if unset). */
    source_language?: string
    /** Whether to overwrite existing translations for this language. */
    overwrite?: boolean
    /** Optional translation-only draft survey payload to translate instead of the last saved survey. */
    survey?: GenerateSurveyTranslationsRequestApiSurvey
}

export interface GeneratedSurveyRootTranslationApi {
    /** Translated survey name. */
    name?: string
    /** Translated thank-you header. */
    thankYouMessageHeader?: string
    /** Translated thank-you description. */
    thankYouMessageDescription?: string
    /** Translated thank-you close button text. */
    thankYouMessageCloseButtonText?: string
}

/**
 * Survey-level translation patch keyed by language.
 */
export type GenerateSurveyTranslationsResponseApiTranslations = { [key: string]: GeneratedSurveyRootTranslationApi }

export interface GeneratedSurveyQuestionTranslationApi {
    /** Translated question text. */
    question?: string
    /** Translated question description. */
    description?: string
    /** Translated submit button text. */
    buttonText?: string
    /** Translated choices in the same order as the source choices. */
    choices?: string[]
    /** Translated lower rating bound label. */
    lowerBoundLabel?: string
    /** Translated upper rating bound label. */
    upperBoundLabel?: string
    /** Translated link text or localized URL. */
    link?: string
}

/**
 * Question translation patch keyed by target language.
 */
export type GeneratedSurveyQuestionTranslationPatchApiTranslations = {
    [key: string]: GeneratedSurveyQuestionTranslationApi
}

export interface GeneratedSurveyQuestionTranslationPatchApi {
    /** Survey question id this patch applies to. */
    id: string
    /** Question translation patch keyed by target language. */
    translations: GeneratedSurveyQuestionTranslationPatchApiTranslations
}

export interface GenerateSurveyTranslationsResponseApi {
    /** Survey-level translation patch keyed by language. */
    translations: GenerateSurveyTranslationsResponseApiTranslations
    /** Question-level translation patches keyed by question id and language. */
    questions: GeneratedSurveyQuestionTranslationPatchApi[]
    /** Editor field paths generated by AI and safe to highlight as draft content. */
    generated_field_paths: string[]
    /** LLM trace id for debugging and feedback. */
    trace_id: string
}

export interface SurveyResponseAnswerApi {
    /** UUID of the survey question this answer belongs to. */
    question_id: string
    /** Zero-based index of the question within the survey. */
    question_index: number
    /** Untranslated question text as configured by the survey author. */
    question_text: string
    /** Question type: open, rating, single_choice, multiple_choice, or link. Determines the shape of the answer field. */
    question_type: string
    /** Resolved answer. String for open/rating/single_choice/link questions, list of strings for multiple_choice questions. Already decoded from the raw $survey_response_<id> property so callers don't need to parse it. */
    answer: unknown
}

export interface SurveyResponseExtraApi {
    /**
     * $device_type at the time the response was sent.
     * @nullable
     */
    device_type?: string | null
    /**
     * $browser at the time the response was sent.
     * @nullable
     */
    browser?: string | null
    /**
     * $os (operating system) at the time the response was sent.
     * @nullable
     */
    os?: string | null
    /**
     * $geoip_country_code at submission time.
     * @nullable
     */
    geoip_country_code?: string | null
    /**
     * $geoip_country_name at submission time.
     * @nullable
     */
    geoip_country_name?: string | null
    /**
     * $geoip_city_name at submission time.
     * @nullable
     */
    geoip_city_name?: string | null
    /**
     * $current_url where the survey was submitted.
     * @nullable
     */
    current_url?: string | null
    /**
     * Survey iteration number when the response was sent. Only set for recurring surveys.
     * @nullable
     */
    iteration?: string | null
}

export interface SurveyResponseRowApi {
    /** UUID of the underlying `survey sent` event. Use as the response identifier for archive operations. */
    uuid: string
    /** distinct_id of the respondent. Cross-pivot to the persons API or session recordings. */
    distinct_id: string
    /**
     * $session_id of the respondent when available. Use to pull the session recording for this response.
     * @nullable
     */
    session_id: string | null
    /** Event timestamp when the response was sent (ISO 8601, UTC). */
    submitted_at: string
    /** One entry per survey question that received a non-empty answer. Question text is already resolved — callers do not need to look up `$survey_response_<id>` keys. */
    answers: SurveyResponseAnswerApi[]
    /** Convenience fields extracted from the event properties (device, browser, geoip, iteration). */
    extra: SurveyResponseExtraApi
}

export interface SurveyResponsesListApi {
    /** Survey response rows for the requested page. */
    results: SurveyResponseRowApi[]
    /** True if more rows exist beyond the current page — fetch the next page with offset + limit. */
    has_more: boolean
    /** The limit applied to this query (echoed back for pagination). */
    limit: number
    /** The offset applied to this query (echoed back for pagination). */
    offset: number
}

/**
 * Event counts keyed by event name (survey shown, survey dismissed, survey sent).
 */
export type SurveyStatsResponseApiStats = { [key: string]: unknown }

/**
 * Calculated response and dismissal rates.
 */
export type SurveyStatsResponseApiRates = { [key: string]: unknown }

export interface SurveyStatsResponseApi {
    /** The survey ID these stats belong to. */
    survey_id: string
    /**
     * When the survey started collecting responses.
     * @nullable
     */
    start_date: string | null
    /**
     * When the survey stopped collecting responses.
     * @nullable
     */
    end_date: string | null
    /** Event counts keyed by event name (survey shown, survey dismissed, survey sent). */
    stats: SurveyStatsResponseApiStats
    /** Calculated response and dismissal rates. */
    rates: SurveyStatsResponseApiRates
    /** Per-question response counts and distributions. Only present when include_per_question_stats=true was passed. For rating questions includes `average`; for choice/rating questions `distribution` maps answer value to count; for open questions `distribution` is empty (use surveys-responses-list to read free-text). */
    per_question_stats?: unknown[]
}

export interface SurveySummarizeRequestApi {
    /** When true, bypass cached summaries and regenerate. Defaults to false. */
    force_refresh?: boolean
}

export interface SurveyQuestionLabelApi {
    /** UUID assigned to the survey question. */
    question_id: string
    /** Untranslated question text as configured by the survey author. */
    question_text: string
    /** Zero-based index of the question within the survey. */
    question_index: number
    /** UUID of the survey this question belongs to. */
    survey_id: string
    /** Display name of the survey. */
    survey_name: string
}

export interface SurveyQuestionLabelsResponseApi {
    /** One entry per question that has an ID assigned, across all the team's surveys. */
    labels: SurveyQuestionLabelApi[]
}

/**
 * Event counts keyed by event name (survey shown, survey dismissed, survey sent).
 */
export type SurveyGlobalStatsResponseApiStats = { [key: string]: unknown }

/**
 * Calculated response and dismissal rates.
 */
export type SurveyGlobalStatsResponseApiRates = { [key: string]: unknown }

export interface SurveyGlobalStatsResponseApi {
    /** Event counts keyed by event name (survey shown, survey dismissed, survey sent). */
    stats: SurveyGlobalStatsResponseApiStats
    /** Calculated response and dismissal rates. */
    rates: SurveyGlobalStatsResponseApiRates
}

export type SurveysListParams = {
    archived?: boolean
    /**
     * Multiple values may be separated by commas.
     */
    ids?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Fuzzy match against survey `name` and `description` using Postgres trigram word similarity. Supports typos and prefix-as-you-type.
     */
    search?: string
    /**
     * * `popover` - popover
     * * `widget` - widget
     * * `external_survey` - external survey
     * * `api` - api
     */
    type?: SurveysListType
}

export type SurveysListType = (typeof SurveysListType)[keyof typeof SurveysListType]

export const SurveysListType = {
    Api: 'api',
    ExternalSurvey: 'external_survey',
    Popover: 'popover',
    Widget: 'widget',
} as const

export type SurveysResponsesListParams = {
    /**
     * When true, exclude responses that have been archived via the archive_response endpoint.
     */
    exclude_archived?: boolean
    /**
     * Maximum number of rows to return (1-500). Defaults to 100.
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of rows to skip for pagination. Combine with `limit` and the `has_more` field to paginate.
     * @minimum 0
     */
    offset?: number
    /**
     * If set, only return rows where this question has a non-empty answer, and only include that question's answer in each row. Required when using score_lte or score_gte.
     * @minLength 1
     */
    question_id?: string
    /**
     * Filter to rows where the rating answer for `question_id` is >= this value. Common use: NPS promoters with score_gte=9. Requires question_id.
     */
    score_gte?: number
    /**
     * Filter to rows where the rating answer for `question_id` is <= this value. Common use: NPS detractors with score_lte=6. Requires question_id.
     */
    score_lte?: number
    /**
     * Only return responses submitted on or after this ISO 8601 timestamp.
     */
    since?: string
    /**
     * Only return responses submitted on or before this ISO 8601 timestamp.
     */
    until?: string
}

export type SurveysStatsRetrieveParams = {
    /**
     * Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
     */
    date_from?: string
    /**
     * Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)
     */
    date_to?: string
    /**
     * When true, also return per-question response counts and answer distributions. Adds one extra HogQL query per question, so leave off unless you need the breakdown.
     */
    include_per_question_stats?: boolean
}

export type SurveysSummarizeResponsesCreateParams = {
    /**
     * Question UUID. Preferred over question_index — stable across question edits.
     */
    question_id?: string
    /**
     * Zero-based question index. Omit to get the survey-wide headline instead.
     */
    question_index?: number
}

export type SurveysGlobalStatsRetrieveParams = {
    /**
     * Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
     */
    date_from?: string
    /**
     * Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)
     */
    date_to?: string
}
