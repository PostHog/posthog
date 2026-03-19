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
 * `widget` - widget
 * `external_survey` - external survey
 * `api` - api
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
 * `client` - Client
 * `all` - All
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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * * `distinct_id` - User ID (default)
 * `device_id` - Device ID
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
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    version?: number | null
    /** Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | NullEnumApi | null
    /** Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | NullEnumApi | null
    readonly evaluation_tags: readonly string[]
    readonly evaluation_contexts: readonly string[]
}

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
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
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

/**
 * * `day` - day
 * `week` - week
 * `month` - month
 */
export type ResponseSamplingIntervalTypeEnumApi =
    (typeof ResponseSamplingIntervalTypeEnumApi)[keyof typeof ResponseSamplingIntervalTypeEnumApi]

export const ResponseSamplingIntervalTypeEnumApi = {
    Day: 'day',
    Week: 'week',
    Month: 'month',
} as const

/**
 * @nullable
 */
export type SurveyApiConditions = { [key: string]: unknown } | null | null

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
        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.

        Basic (open-ended question)
        - `id`: The question ID
        - `type`: `open`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `branching`: Branching logic for the question. See branching types below for details.

        Link (a question with a link)
        - `id`: The question ID
        - `type`: `link`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `link`: The URL associated with the question.
        - `branching`: Branching logic for the question. See branching types below for details.

        Rating (a question with a rating scale)
        - `id`: The question ID
        - `type`: `rating`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `display`: Display style of the rating (`number` or `emoji`).
        - `scale`: The scale of the rating (`number`).
        - `lowerBoundLabel`: Label for the lower bound of the scale.
        - `upperBoundLabel`: Label for the upper bound of the scale.
        - `isNpsQuestion`: Whether the question is an NPS rating.
        - `branching`: Branching logic for the question. See branching types below for details.

        Multiple choice
        - `id`: The question ID
        - `type`: `single_choice` or `multiple_choice`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `choices`: An array of choices for the question.
        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
        - `branching`: Branching logic for the question. See branching types below for details.

        Branching logic can be one of the following types:

        Next question: Proceeds to the next question
        ```json
        {
            "type": "next_question"
        }
        ```

        End: Ends the survey, optionally displaying a confirmation message.
        ```json
        {
            "type": "end"
        }
        ```

        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
        ```json
        {
            "type": "response_based",
            "responseValues": {
                "responseKey": "value"
            }
        }
        ```

        Specific question: Proceeds to a specific question by index.
        ```json
        {
            "type": "specific_question",
            "index": 2
        }
        ```

        Translations: Each question can include inline translations.
        - `translations`: Object mapping language codes to translated fields.
        - Language codes: Any string - allows customers to use their own language keys (e.g., "es", "es-MX", "english", "french")
        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`

        Example with translations:
        ```json
        {
            "id": "uuid",
            "type": "rating",
            "question": "How satisfied are you?",
            "lowerBoundLabel": "Not satisfied",
            "upperBoundLabel": "Very satisfied",
            "translations": {
                "es": {
                    "question": "¿Qué tan satisfecho estás?",
                    "lowerBoundLabel": "No satisfecho",
                    "upperBoundLabel": "Muy satisfecho"
                },
                "fr": {
                    "question": "Dans quelle mesure êtes-vous satisfait?"
                }
            }
        }
        ```
         */
    questions?: unknown | null
    /** @nullable */
    readonly conditions: SurveyApiConditions
    appearance?: unknown | null
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
    response_sampling_interval_type?: ResponseSamplingIntervalTypeEnumApi | BlankEnumApi | NullEnumApi | null
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
    response_sampling_daily_limits?: unknown | null
    /** @nullable */
    enable_partial_responses?: boolean | null
    /** @nullable */
    enable_iframe_embedding?: boolean | null
    translations?: unknown | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    form_content?: unknown | null
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
 * * `cohort` - cohort
 * `person` - person
 * `group` - group
 */
export type Type380EnumApi = (typeof Type380EnumApi)[keyof typeof Type380EnumApi]

export const Type380EnumApi = {
    Cohort: 'cohort',
    Person: 'person',
    Group: 'group',
} as const

/**
 * * `exact` - exact
 * `is_not` - is_not
 * `icontains` - icontains
 * `not_icontains` - not_icontains
 * `regex` - regex
 * `not_regex` - not_regex
 * `gt` - gt
 * `gte` - gte
 * `lt` - lt
 * `lte` - lte
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

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
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

* `exact` - exact
* `is_not` - is_not
* `icontains` - icontains
* `not_icontains` - not_icontains
* `regex` - regex
* `not_regex` - not_regex
* `gt` - gt
* `gte` - gte
* `lt` - lt
* `lte` - lte */
    operator: FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi
}

/**
 * * `is_set` - is_set
 * `is_not_set` - is_not_set
 */
export type Operator3e6EnumApi = (typeof Operator3e6EnumApi)[keyof typeof Operator3e6EnumApi]

export const Operator3e6EnumApi = {
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
} as const

export interface FeatureFlagFilterPropertyExistsSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
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

* `is_set` - is_set
* `is_not_set` - is_not_set */
    operator: Operator3e6EnumApi
    /** Optional value. Runtime behavior determines whether this is ignored. */
    value?: unknown
}

/**
 * * `is_date_exact` - is_date_exact
 * `is_date_after` - is_date_after
 * `is_date_before` - is_date_before
 */
export type FeatureFlagFilterPropertyDateSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyDateSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyDateSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyDateSchemaOperatorEnumApi = {
    IsDateExact: 'is_date_exact',
    IsDateAfter: 'is_date_after',
    IsDateBefore: 'is_date_before',
} as const

export interface FeatureFlagFilterPropertyDateSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
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

* `is_date_exact` - is_date_exact
* `is_date_after` - is_date_after
* `is_date_before` - is_date_before */
    operator: FeatureFlagFilterPropertyDateSchemaOperatorEnumApi
    /** Date value in ISO format or relative date expression. */
    value: string
}

/**
 * * `semver_gt` - semver_gt
 * `semver_gte` - semver_gte
 * `semver_lt` - semver_lt
 * `semver_lte` - semver_lte
 * `semver_eq` - semver_eq
 * `semver_neq` - semver_neq
 * `semver_tilde` - semver_tilde
 * `semver_caret` - semver_caret
 * `semver_wildcard` - semver_wildcard
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

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
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

* `semver_gt` - semver_gt
* `semver_gte` - semver_gte
* `semver_lt` - semver_lt
* `semver_lte` - semver_lte
* `semver_eq` - semver_eq
* `semver_neq` - semver_neq
* `semver_tilde` - semver_tilde
* `semver_caret` - semver_caret
* `semver_wildcard` - semver_wildcard */
    operator: FeatureFlagFilterPropertySemverSchemaOperatorEnumApi
    /** Semantic version string. */
    value: string
}

/**
 * * `icontains_multi` - icontains_multi
 * `not_icontains_multi` - not_icontains_multi
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

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
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

* `icontains_multi` - icontains_multi
* `not_icontains_multi` - not_icontains_multi */
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
 * `not_in` - not_in
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

* `cohort` - cohort */
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

* `in` - in
* `not_in` - not_in */
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

* `flag` - flag */
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

* `flag_evaluates_to` - flag_evaluates_to */
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

export type FeatureFlagFiltersSchemaApiSuperGroupsItem = { [key: string]: unknown }

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
    /** Additional super condition groups used by experiments. */
    super_groups?: FeatureFlagFiltersSchemaApiSuperGroupsItem[]
}

export interface SurveySerializerCreateUpdateOnlySchemaApi {
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
    targeting_flag_filters?: FeatureFlagFiltersSchemaApi | null
    /** @nullable */
    remove_targeting_flag?: boolean | null
    /**
        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.

        Basic (open-ended question)
        - `id`: The question ID
        - `type`: `open`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `branching`: Branching logic for the question. See branching types below for details.

        Link (a question with a link)
        - `id`: The question ID
        - `type`: `link`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `link`: The URL associated with the question.
        - `branching`: Branching logic for the question. See branching types below for details.

        Rating (a question with a rating scale)
        - `id`: The question ID
        - `type`: `rating`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `display`: Display style of the rating (`number` or `emoji`).
        - `scale`: The scale of the rating (`number`).
        - `lowerBoundLabel`: Label for the lower bound of the scale.
        - `upperBoundLabel`: Label for the upper bound of the scale.
        - `isNpsQuestion`: Whether the question is an NPS rating.
        - `branching`: Branching logic for the question. See branching types below for details.

        Multiple choice
        - `id`: The question ID
        - `type`: `single_choice` or `multiple_choice`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `choices`: An array of choices for the question.
        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
        - `branching`: Branching logic for the question. See branching types below for details.

        Branching logic can be one of the following types:

        Next question: Proceeds to the next question
        ```json
        {
            "type": "next_question"
        }
        ```

        End: Ends the survey, optionally displaying a confirmation message.
        ```json
        {
            "type": "end"
        }
        ```

        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
        ```json
        {
            "type": "response_based",
            "responseValues": {
                "responseKey": "value"
            }
        }
        ```

        Specific question: Proceeds to a specific question by index.
        ```json
        {
            "type": "specific_question",
            "index": 2
        }
        ```

        Translations: Each question can include inline translations.
        - `translations`: Object mapping language codes to translated fields.
        - Language codes: Any string - allows customers to use their own language keys (e.g., "es", "es-MX", "english", "french")
        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`

        Example with translations:
        ```json
        {
            "id": "uuid",
            "type": "rating",
            "question": "How satisfied are you?",
            "lowerBoundLabel": "Not satisfied",
            "upperBoundLabel": "Very satisfied",
            "translations": {
                "es": {
                    "question": "¿Qué tan satisfecho estás?",
                    "lowerBoundLabel": "No satisfecho",
                    "upperBoundLabel": "Muy satisfecho"
                },
                "fr": {
                    "question": "Dans quelle mesure êtes-vous satisfait?"
                }
            }
        }
        ```
         */
    questions?: unknown | null
    conditions?: unknown | null
    appearance?: unknown | null
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
    response_sampling_interval_type?: ResponseSamplingIntervalTypeEnumApi | BlankEnumApi | NullEnumApi | null
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
    response_sampling_daily_limits?: unknown | null
    /** @nullable */
    enable_partial_responses?: boolean | null
    /** @nullable */
    enable_iframe_embedding?: boolean | null
    translations?: unknown | null
    _create_in_folder?: string
    form_content?: unknown | null
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
    targeting_flag_filters?: unknown | null
    /** @nullable */
    remove_targeting_flag?: boolean | null
    /**
        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.

        Basic (open-ended question)
        - `id`: The question ID
        - `type`: `open`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `branching`: Branching logic for the question. See branching types below for details.

        Link (a question with a link)
        - `id`: The question ID
        - `type`: `link`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `link`: The URL associated with the question.
        - `branching`: Branching logic for the question. See branching types below for details.

        Rating (a question with a rating scale)
        - `id`: The question ID
        - `type`: `rating`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `display`: Display style of the rating (`number` or `emoji`).
        - `scale`: The scale of the rating (`number`).
        - `lowerBoundLabel`: Label for the lower bound of the scale.
        - `upperBoundLabel`: Label for the upper bound of the scale.
        - `isNpsQuestion`: Whether the question is an NPS rating.
        - `branching`: Branching logic for the question. See branching types below for details.

        Multiple choice
        - `id`: The question ID
        - `type`: `single_choice` or `multiple_choice`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `choices`: An array of choices for the question.
        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
        - `branching`: Branching logic for the question. See branching types below for details.

        Branching logic can be one of the following types:

        Next question: Proceeds to the next question
        ```json
        {
            "type": "next_question"
        }
        ```

        End: Ends the survey, optionally displaying a confirmation message.
        ```json
        {
            "type": "end"
        }
        ```

        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
        ```json
        {
            "type": "response_based",
            "responseValues": {
                "responseKey": "value"
            }
        }
        ```

        Specific question: Proceeds to a specific question by index.
        ```json
        {
            "type": "specific_question",
            "index": 2
        }
        ```

        Translations: Each question can include inline translations.
        - `translations`: Object mapping language codes to translated fields.
        - Language codes: Any string - allows customers to use their own language keys (e.g., "es", "es-MX", "english", "french")
        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`

        Example with translations:
        ```json
        {
            "id": "uuid",
            "type": "rating",
            "question": "How satisfied are you?",
            "lowerBoundLabel": "Not satisfied",
            "upperBoundLabel": "Very satisfied",
            "translations": {
                "es": {
                    "question": "¿Qué tan satisfecho estás?",
                    "lowerBoundLabel": "No satisfecho",
                    "upperBoundLabel": "Muy satisfecho"
                },
                "fr": {
                    "question": "Dans quelle mesure êtes-vous satisfait?"
                }
            }
        }
        ```
         */
    questions?: unknown | null
    conditions?: unknown | null
    appearance?: unknown | null
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
    response_sampling_interval_type?: ResponseSamplingIntervalTypeEnumApi | BlankEnumApi | NullEnumApi | null
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
    response_sampling_daily_limits?: unknown | null
    /** @nullable */
    enable_partial_responses?: boolean | null
    /** @nullable */
    enable_iframe_embedding?: boolean | null
    translations?: unknown | null
    _create_in_folder?: string
    form_content?: unknown | null
}

export interface PatchedSurveySerializerCreateUpdateOnlySchemaApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    description?: string
    type?: SurveyTypeApi
    /** @nullable */
    schedule?: string | null
    readonly linked_flag?: MinimalFeatureFlagApi
    /** @nullable */
    linked_flag_id?: number | null
    /** @nullable */
    linked_insight_id?: number | null
    targeting_flag_id?: number
    readonly targeting_flag?: MinimalFeatureFlagApi
    readonly internal_targeting_flag?: MinimalFeatureFlagApi
    targeting_flag_filters?: FeatureFlagFiltersSchemaApi | null
    /** @nullable */
    remove_targeting_flag?: boolean | null
    /**
        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.

        Basic (open-ended question)
        - `id`: The question ID
        - `type`: `open`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `branching`: Branching logic for the question. See branching types below for details.

        Link (a question with a link)
        - `id`: The question ID
        - `type`: `link`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `link`: The URL associated with the question.
        - `branching`: Branching logic for the question. See branching types below for details.

        Rating (a question with a rating scale)
        - `id`: The question ID
        - `type`: `rating`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `display`: Display style of the rating (`number` or `emoji`).
        - `scale`: The scale of the rating (`number`).
        - `lowerBoundLabel`: Label for the lower bound of the scale.
        - `upperBoundLabel`: Label for the upper bound of the scale.
        - `isNpsQuestion`: Whether the question is an NPS rating.
        - `branching`: Branching logic for the question. See branching types below for details.

        Multiple choice
        - `id`: The question ID
        - `type`: `single_choice` or `multiple_choice`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `choices`: An array of choices for the question.
        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
        - `branching`: Branching logic for the question. See branching types below for details.

        Branching logic can be one of the following types:

        Next question: Proceeds to the next question
        ```json
        {
            "type": "next_question"
        }
        ```

        End: Ends the survey, optionally displaying a confirmation message.
        ```json
        {
            "type": "end"
        }
        ```

        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
        ```json
        {
            "type": "response_based",
            "responseValues": {
                "responseKey": "value"
            }
        }
        ```

        Specific question: Proceeds to a specific question by index.
        ```json
        {
            "type": "specific_question",
            "index": 2
        }
        ```

        Translations: Each question can include inline translations.
        - `translations`: Object mapping language codes to translated fields.
        - Language codes: Any string - allows customers to use their own language keys (e.g., "es", "es-MX", "english", "french")
        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`

        Example with translations:
        ```json
        {
            "id": "uuid",
            "type": "rating",
            "question": "How satisfied are you?",
            "lowerBoundLabel": "Not satisfied",
            "upperBoundLabel": "Very satisfied",
            "translations": {
                "es": {
                    "question": "¿Qué tan satisfecho estás?",
                    "lowerBoundLabel": "No satisfecho",
                    "upperBoundLabel": "Muy satisfecho"
                },
                "fr": {
                    "question": "Dans quelle mesure êtes-vous satisfait?"
                }
            }
        }
        ```
         */
    questions?: unknown | null
    conditions?: unknown | null
    appearance?: unknown | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
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
    response_sampling_interval_type?: ResponseSamplingIntervalTypeEnumApi | BlankEnumApi | NullEnumApi | null
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
    response_sampling_daily_limits?: unknown | null
    /** @nullable */
    enable_partial_responses?: boolean | null
    /** @nullable */
    enable_iframe_embedding?: boolean | null
    translations?: unknown | null
    _create_in_folder?: string
    form_content?: unknown | null
}

export type SurveysListParams = {
    archived?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}
