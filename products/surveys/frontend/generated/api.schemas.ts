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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SurveyTypeApi = {
    popover: 'popover',
    widget: 'widget',
    external_survey: 'external_survey',
    api: 'api',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ResponseSamplingIntervalTypeEnumApi = {
    day: 'day',
    week: 'week',
    month: 'month',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const NullEnumApi = {} as const

/**
 * * `server` - Server
 * `client` - Client
 * `all` - All
 */
export type EvaluationRuntimeEnumApi = (typeof EvaluationRuntimeEnumApi)[keyof typeof EvaluationRuntimeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EvaluationRuntimeEnumApi = {
    server: 'server',
    client: 'client',
    all: 'all',
} as const

/**
 * * `distinct_id` - User ID (default)
 * `device_id` - Device ID
 */
export type BucketingIdentifierEnumApi = (typeof BucketingIdentifierEnumApi)[keyof typeof BucketingIdentifierEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BucketingIdentifierEnumApi = {
    distinct_id: 'distinct_id',
    device_id: 'device_id',
} as const

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

// eslint-disable-next-line @typescript-eslint/no-redeclare
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
 * * `day` - day
 * `week` - week
 * `month` - month
 */
export type ResponseSamplingIntervalTypeEnumApi =
    (typeof ResponseSamplingIntervalTypeEnumApi)[keyof typeof ResponseSamplingIntervalTypeEnumApi]

export interface PaginatedSurveyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SurveyApi[]
}

/**
 * @nullable
 */
export type SurveySerializerCreateUpdateOnlyApiTargetingFlagFilters = unknown | null

/**
 * 
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
        
 * @nullable
 */
export type SurveySerializerCreateUpdateOnlyApiQuestions = unknown | null

/**
 * @nullable
 */
export type SurveySerializerCreateUpdateOnlyApiConditions = unknown | null

/**
 * @nullable
 */
export type SurveySerializerCreateUpdateOnlyApiAppearance = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType = {
    ...ResponseSamplingIntervalTypeEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * @nullable
 */
export type SurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType =
    | (typeof SurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType)[keyof typeof SurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType]
    | null

/**
 * @nullable
 */
export type SurveySerializerCreateUpdateOnlyApiResponseSamplingDailyLimits = unknown | null

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
    /** @nullable */
    targeting_flag_filters?: SurveySerializerCreateUpdateOnlyApiTargetingFlagFilters
    /** @nullable */
    remove_targeting_flag?: boolean | null
    /**
   * 
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
        
   * @nullable
   */
    questions?: SurveySerializerCreateUpdateOnlyApiQuestions
    /** @nullable */
    conditions?: SurveySerializerCreateUpdateOnlyApiConditions
    /** @nullable */
    appearance?: SurveySerializerCreateUpdateOnlyApiAppearance
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
    /** @nullable */
    response_sampling_interval_type?: SurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType
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
    /** @nullable */
    response_sampling_daily_limits?: SurveySerializerCreateUpdateOnlyApiResponseSamplingDailyLimits
    /** @nullable */
    enable_partial_responses?: boolean | null
    _create_in_folder?: string
}

/**
 * 
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
        
 * @nullable
 */
export type SurveyApiQuestions = unknown | null

/**
 * @nullable
 */
export type SurveyApiAppearance = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SurveyApiResponseSamplingIntervalType = {
    ...ResponseSamplingIntervalTypeEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * @nullable
 */
export type SurveyApiResponseSamplingIntervalType =
    | (typeof SurveyApiResponseSamplingIntervalType)[keyof typeof SurveyApiResponseSamplingIntervalType]
    | null

/**
 * @nullable
 */
export type SurveyApiResponseSamplingDailyLimits = unknown | null

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
   * 
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
        
   * @nullable
   */
    questions?: SurveyApiQuestions
    readonly conditions: string
    /** @nullable */
    appearance?: SurveyApiAppearance
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
    /** @nullable */
    response_sampling_interval_type?: SurveyApiResponseSamplingIntervalType
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
    /** @nullable */
    response_sampling_daily_limits?: SurveyApiResponseSamplingDailyLimits
    /** @nullable */
    enable_partial_responses?: boolean | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

/**
 * @nullable
 */
export type PatchedSurveySerializerCreateUpdateOnlyApiTargetingFlagFilters = unknown | null

/**
 * 
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
        
 * @nullable
 */
export type PatchedSurveySerializerCreateUpdateOnlyApiQuestions = unknown | null

/**
 * @nullable
 */
export type PatchedSurveySerializerCreateUpdateOnlyApiConditions = unknown | null

/**
 * @nullable
 */
export type PatchedSurveySerializerCreateUpdateOnlyApiAppearance = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PatchedSurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType = {
    ...ResponseSamplingIntervalTypeEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * @nullable
 */
export type PatchedSurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType =
    | (typeof PatchedSurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType)[keyof typeof PatchedSurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType]
    | null

/**
 * @nullable
 */
export type PatchedSurveySerializerCreateUpdateOnlyApiResponseSamplingDailyLimits = unknown | null

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
    /** @nullable */
    targeting_flag_filters?: PatchedSurveySerializerCreateUpdateOnlyApiTargetingFlagFilters
    /** @nullable */
    remove_targeting_flag?: boolean | null
    /**
   * 
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
        
   * @nullable
   */
    questions?: PatchedSurveySerializerCreateUpdateOnlyApiQuestions
    /** @nullable */
    conditions?: PatchedSurveySerializerCreateUpdateOnlyApiConditions
    /** @nullable */
    appearance?: PatchedSurveySerializerCreateUpdateOnlyApiAppearance
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
    /** @nullable */
    response_sampling_interval_type?: PatchedSurveySerializerCreateUpdateOnlyApiResponseSamplingIntervalType
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
    /** @nullable */
    response_sampling_daily_limits?: PatchedSurveySerializerCreateUpdateOnlyApiResponseSamplingDailyLimits
    /** @nullable */
    enable_partial_responses?: boolean | null
    _create_in_folder?: string
}

export type MinimalFeatureFlagApiFilters = { [key: string]: unknown }

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MinimalFeatureFlagApiEvaluationRuntime = {
    ...EvaluationRuntimeEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All
 * @nullable
 */
export type MinimalFeatureFlagApiEvaluationRuntime =
    | (typeof MinimalFeatureFlagApiEvaluationRuntime)[keyof typeof MinimalFeatureFlagApiEvaluationRuntime]
    | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MinimalFeatureFlagApiBucketingIdentifier = {
    ...BucketingIdentifierEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID
 * @nullable
 */
export type MinimalFeatureFlagApiBucketingIdentifier =
    | (typeof MinimalFeatureFlagApiBucketingIdentifier)[keyof typeof MinimalFeatureFlagApiBucketingIdentifier]
    | null

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
    /**
   * Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All
   * @nullable
   */
    evaluation_runtime?: MinimalFeatureFlagApiEvaluationRuntime
    /**
   * Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID
   * @nullable
   */
    bucketing_identifier?: MinimalFeatureFlagApiBucketingIdentifier
    readonly evaluation_tags: readonly string[]
}

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const UserBasicApiRoleAtOrganization = { ...RoleAtOrganizationEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type UserBasicApiRoleAtOrganization =
    | (typeof UserBasicApiRoleAtOrganization)[keyof typeof UserBasicApiRoleAtOrganization]
    | null

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
    /** @nullable */
    role_at_organization?: UserBasicApiRoleAtOrganization
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
