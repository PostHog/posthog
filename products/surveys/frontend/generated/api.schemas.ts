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
    popover: 'popover',
    widget: 'widget',
    external_survey: 'external_survey',
    api: 'api',
} as const

/**
 * * `server` - Server
 * `client` - Client
 * `all` - All
 */
export type EvaluationRuntimeEnumApi = (typeof EvaluationRuntimeEnumApi)[keyof typeof EvaluationRuntimeEnumApi]

export const EvaluationRuntimeEnumApi = {
    server: 'server',
    client: 'client',
    all: 'all',
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
    distinct_id: 'distinct_id',
    device_id: 'device_id',
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
    engineering: 'engineering',
    data: 'data',
    product: 'product',
    founder: 'founder',
    leadership: 'leadership',
    marketing: 'marketing',
    sales: 'sales',
    other: 'other',
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
    day: 'day',
    week: 'week',
    month: 'month',
} as const

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
         */
    questions?: unknown | null
    readonly conditions: string
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
    readonly feature_flag_keys: readonly unknown[]
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
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedSurveyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SurveyApi[]
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
    _create_in_folder?: string
}

export interface PatchedSurveySerializerCreateUpdateOnlyApi {
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
    _create_in_folder?: string
}

export type SurveysListParams = {
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
