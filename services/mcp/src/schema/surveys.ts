import { z } from 'zod'

import { FilterGroupsSchema } from './flags.js'

// Survey question types
const BaseSurveyQuestionSchema = z.object({
    question: z.string(),
    description: z.string().optional(),
    descriptionContentType: z.enum(['html', 'text']).optional(),
    optional: z.boolean().optional(),
    buttonText: z.string().optional(),
})

// Branching logic schemas
const NextQuestionBranching = z.object({
    type: z.literal('next_question'),
})

const EndBranching = z.object({
    type: z.literal('end'),
})

// Choice response branching - uses numeric choice indices (0, 1, 2, etc.)
const ChoiceResponseBranching = z
    .object({
        type: z.literal('response_based'),
        responseValues: z
            .record(z.string(), z.union([z.number(), z.literal('end')]))
            .describe(
                "Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior)."
            ),
    })
    .describe('For single choice questions: use choice indices as string keys ("0", "1", "2", etc.)')

// NPS sentiment branching - uses sentiment categories
const NPSSentimentValue = z.union([z.number(), z.literal('end')])

const NPSSentimentBranching = z
    .object({
        type: z.literal('response_based'),
        responseValues: z
            .object({
                detractors: NPSSentimentValue.optional().describe('NPS detractors (0-6)'),
                passives: NPSSentimentValue.optional().describe('NPS passives (7-8)'),
                promoters: NPSSentimentValue.optional().describe('NPS promoters (9-10)'),
            })
            .describe(
                "Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior)."
            ),
    })
    .describe(
        'For NPS rating questions: use sentiment keys based on score ranges - detractors (0-6), passives (7-8), promoters (9-10)'
    )

// Match type enum for URL and device type targeting
const MatchTypeEnum = z
    .enum(['regex', 'not_regex', 'exact', 'is_not', 'icontains', 'not_icontains'])
    .describe(
        "URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain)"
    )

// Rating sentiment branching - uses sentiment categories
const RatingSentimentValue = z.union([z.number(), z.literal('end')])

const RatingSentimentBranching = z
    .object({
        type: z.literal('response_based'),
        responseValues: z
            .object({
                negative: RatingSentimentValue.optional().describe('Lower third of scale'),
                neutral: RatingSentimentValue.optional().describe('Middle third of scale'),
                positive: RatingSentimentValue.optional().describe('Upper third of scale'),
            })
            .describe(
                "Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior)."
            ),
    })
    .describe(
        'For rating questions: use sentiment keys based on scale thirds - negative (lower third), neutral (middle third), positive (upper third)'
    )

const SpecificQuestionBranching = z.object({
    type: z.literal('specific_question'),
    index: z.number(),
})

// Branching schema unions for different question types
const ChoiceBranching = z.union([
    NextQuestionBranching,
    EndBranching,
    ChoiceResponseBranching,
    SpecificQuestionBranching,
])

const NPSBranching = z.union([NextQuestionBranching, EndBranching, NPSSentimentBranching, SpecificQuestionBranching])

const RatingBranching = z.union([
    NextQuestionBranching,
    EndBranching,
    RatingSentimentBranching,
    SpecificQuestionBranching,
])

// Question schemas - cleaner naming without Schema suffix
const OpenQuestion = BaseSurveyQuestionSchema.extend({
    type: z.literal('open'),
})

const LinkQuestion = BaseSurveyQuestionSchema.extend({
    type: z.literal('link'),
    link: z.string().url(),
})

const RatingQuestion = BaseSurveyQuestionSchema.extend({
    type: z.literal('rating'),
    display: z
        .enum(['number', 'emoji'])
        .optional()
        .describe("Display format: 'number' shows numeric scale, 'emoji' shows emoji scale"),
    scale: z
        .union([z.literal(3), z.literal(5), z.literal(7)])
        .optional()
        .describe('Rating scale can be one of 3, 5, or 7'),
    lowerBoundLabel: z.string().optional().describe("Label for the lowest rating (e.g., 'Very Poor')"),
    upperBoundLabel: z.string().optional().describe("Label for the highest rating (e.g., 'Excellent')"),
    branching: RatingBranching.optional(),
}).superRefine((data, ctx) => {
    // Validate display-specific scale constraints
    if (data.display === 'emoji' && data.scale && ![3, 5].includes(data.scale)) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'Emoji display only supports scales of 3 or 5',
            path: ['scale'],
        })
    }

    if (data.display === 'number' && data.scale && ![5, 7].includes(data.scale)) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'Number display only supports scales of 5 or 7',
            path: ['scale'],
        })
    }

    // Validate response-based branching for rating questions
    if (data.branching?.type === 'response_based') {
        const responseValues = data.branching.responseValues
        const validSentiments = ['negative', 'neutral', 'positive']

        // Check that all response keys are valid sentiment categories
        for (const key of Object.keys(responseValues)) {
            if (!validSentiments.includes(key)) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    message: `Invalid sentiment key "${key}". Must be one of: ${validSentiments.join(', ')}`,
                    path: ['branching', 'responseValues', key],
                })
            }
        }
    }
})

const NPSRatingQuestion = BaseSurveyQuestionSchema.extend({
    type: z.literal('rating'),
    display: z.literal('number').describe('NPS questions always use numeric scale'),
    scale: z.literal(10).describe('NPS questions always use 0-10 scale'),
    lowerBoundLabel: z.string().optional().describe("Label for 0 rating (typically 'Not at all likely')"),
    upperBoundLabel: z.string().optional().describe("Label for 10 rating (typically 'Extremely likely')"),
    branching: NPSBranching.optional(),
}).superRefine((data, ctx) => {
    // Validate response-based branching for NPS rating questions
    if (data.branching?.type === 'response_based') {
        const responseValues = data.branching.responseValues
        const validNPSCategories = ['detractors', 'passives', 'promoters']

        // Check that all response keys are valid NPS sentiment categories
        for (const key of Object.keys(responseValues)) {
            if (!validNPSCategories.includes(key)) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    message: `Invalid NPS category "${key}". Must be one of: ${validNPSCategories.join(', ')}`,
                    path: ['branching', 'responseValues', key],
                })
            }
        }
    }
})

const SingleChoiceQuestion = BaseSurveyQuestionSchema.extend({
    type: z.literal('single_choice'),
    choices: z
        .array(z.string().min(1, 'Choice text cannot be empty'))
        .min(2, 'Must have at least 2 choices')
        .max(20, 'Cannot have more than 20 choices')
        .describe('Array of choice options. Choice indices (0, 1, 2, etc.) are used for branching logic'),
    shuffleOptions: z.boolean().optional().describe('Whether to randomize the order of choices for each respondent'),
    hasOpenChoice: z
        .boolean()
        .optional()
        .describe("Whether the last choice (typically 'Other', is an open text input question"),
    branching: ChoiceBranching.optional(),
}).superRefine((data, ctx) => {
    // Validate unique choices
    const uniqueChoices = new Set(data.choices)
    if (uniqueChoices.size !== data.choices.length) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'All choices must be unique',
            path: ['choices'],
        })
    }

    // Validate hasOpenChoice logic
    if (data.hasOpenChoice && data.choices.length === 0) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'Cannot have open choice without any regular choices',
            path: ['hasOpenChoice'],
        })
    }

    // Validate response-based branching for single choice questions
    if (data.branching?.type === 'response_based') {
        const responseValues = data.branching.responseValues
        const choiceCount = data.choices.length

        // Check that all response keys are valid choice indices
        for (const key of Object.keys(responseValues)) {
            const choiceIndex = Number.parseInt(key, 10)
            if (Number.isNaN(choiceIndex) || choiceIndex < 0 || choiceIndex >= choiceCount) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    message: `Invalid choice index "${key}". Must be between 0 and ${choiceCount - 1}`,
                    path: ['branching', 'responseValues', key],
                })
            }
        }
    }
})

const MultipleChoiceQuestion = BaseSurveyQuestionSchema.extend({
    type: z.literal('multiple_choice'),
    choices: z
        .array(z.string().min(1, 'Choice text cannot be empty'))
        .min(2, 'Must have at least 2 choices')
        .max(20, 'Cannot have more than 20 choices')
        .describe('Array of choice options. Multiple selections allowed. No branching logic supported.'),
    shuffleOptions: z.boolean().optional().describe('Whether to randomize the order of choices for each respondent'),
    hasOpenChoice: z
        .boolean()
        .optional()
        .describe("Whether the last choice (typically 'Other', is an open text input question"),
})

// Input schema - strict validation for user input
export const SurveyQuestionInputSchema = z
    .union([
        OpenQuestion,
        LinkQuestion,
        RatingQuestion,
        NPSRatingQuestion,
        SingleChoiceQuestion,
        MultipleChoiceQuestion,
    ])
    .superRefine((data, ctx) => {
        // Validate that branching is only used with supported question types
        if (!('branching' in data) || !data.branching) {
            return
        }

        const supportedTypes = ['rating', 'single_choice']
        if (!supportedTypes.includes(data.type)) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                message: `Branching is not supported for question type "${data.type}". Only supported for: ${supportedTypes.join(', ')}`,
                path: ['branching'],
            })
        }
    })

// Survey targeting conditions - used in input schema
const SurveyConditions = z.object({
    url: z.string().optional(),
    selector: z.string().optional(),
    seenSurveyWaitPeriodInDays: z
        .number()
        .optional()
        .describe("Don't show this survey to users who saw any survey in the last x days."),
    urlMatchType: MatchTypeEnum.optional(),
    events: z
        .object({
            repeatedActivation: z
                .boolean()
                .optional()
                .describe(
                    'Whether to show the survey every time one of the events is triggered (true), or just once (false)'
                ),
            values: z
                .array(
                    z.object({
                        name: z.string(),
                    })
                )
                .optional()
                .describe('Array of event names that trigger the survey'),
        })
        .optional(),
    deviceTypes: z.array(z.enum(['Desktop', 'Mobile', 'Tablet'])).optional(),
    deviceTypesMatchType: MatchTypeEnum.optional(),
    linkedFlagVariant: z.string().optional().describe('The variant of the feature flag linked to this survey'),
})

// Survey appearance customization - input schema
const SurveyAppearance = z.object({
    backgroundColor: z.string().optional(),
    submitButtonColor: z.string().optional(),
    textColor: z.string().optional(), // deprecated, use auto contrast text color instead
    submitButtonText: z.string().optional(),
    submitButtonTextColor: z.string().optional(),
    descriptionTextColor: z.string().optional(),
    ratingButtonColor: z.string().optional(),
    ratingButtonActiveColor: z.string().optional(),
    ratingButtonHoverColor: z.string().optional(),
    whiteLabel: z.boolean().optional(),
    autoDisappear: z.boolean().optional(),
    displayThankYouMessage: z.boolean().optional(),
    thankYouMessageHeader: z.string().optional(),
    thankYouMessageDescription: z.string().optional(),
    thankYouMessageDescriptionContentType: z.enum(['html', 'text']).optional(),
    thankYouMessageCloseButtonText: z.string().optional(),
    borderColor: z.string().optional(),
    placeholder: z.string().optional(),
    shuffleQuestions: z.boolean().optional(),
    surveyPopupDelaySeconds: z.number().optional(),
    widgetType: z.enum(['button', 'tab', 'selector']).optional(),
    widgetSelector: z.string().optional(),
    widgetLabel: z.string().optional(),
    widgetColor: z.string().optional(),
    fontFamily: z.string().optional(),
    maxWidth: z.string().optional(),
    zIndex: z.string().optional(),
    disabledButtonOpacity: z.string().optional(),
    boxPadding: z.string().optional(),
})

// Survey input schemas
export const CreateSurveyInputSchema = z.object({
    name: z.string().min(1, 'Survey name cannot be empty'),
    description: z.string().optional(),
    type: z.enum(['popover', 'api', 'widget', 'external_survey']).optional(),
    questions: z.array(SurveyQuestionInputSchema).min(1, 'Survey must have at least one question'),
    appearance: SurveyAppearance.optional(),
    start_date: z
        .string()
        .datetime()
        .nullable()
        .optional()
        .default(null)
        .describe(
            "Setting this will launch the survey immediately. Don't add a start_date unless explicitly requested to do so."
        ),
    responses_limit: z
        .number()
        .positive('Response limit must be positive')
        .nullable()
        .optional()
        .describe('The maximum number of responses before automatically stopping the survey.'),
    iteration_count: z
        .number()
        .positive('Iteration count must be positive')
        .nullable()
        .optional()
        .describe(
            "For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule."
        ),
    iteration_frequency_days: z
        .number()
        .positive('Iteration frequency must be positive')
        .max(365, 'Iteration frequency cannot exceed 365 days')
        .nullable()
        .optional()
        .describe(
            'For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.'
        ),
    enable_partial_responses: z
        .boolean()
        .optional()
        .describe(
            'When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).'
        ),
    linked_flag_id: z.number().nullable().optional().describe('The feature flag linked to this survey'),
    targeting_flag_filters: FilterGroupsSchema.optional().describe(
        "Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 100}]}"
    ),
})

export const UpdateSurveyInputSchema = z.object({
    name: z.string().min(1, 'Survey name cannot be empty').optional(),
    description: z.string().optional(),
    type: z.enum(['popover', 'api', 'widget', 'external_survey']).optional(),
    questions: z.array(SurveyQuestionInputSchema).min(1, 'Survey must have at least one question').optional(),
    conditions: SurveyConditions.optional(),
    appearance: SurveyAppearance.optional(),
    schedule: z
        .enum(['once', 'recurring', 'always'])
        .optional()
        .describe(
            "Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)"
        ),
    start_date: z
        .string()
        .datetime()
        .optional()
        .describe('When the survey should start being shown to users. Setting this will launch the survey'),
    end_date: z
        .string()
        .datetime()
        .optional()
        .describe('When the survey stopped being shown to users. Setting this will complete the survey.'),
    archived: z.boolean().optional(),
    responses_limit: z
        .number()
        .positive('Response limit must be positive')
        .nullable()
        .optional()
        .describe('The maximum number of responses before automatically stopping the survey.'),
    iteration_count: z
        .number()
        .positive('Iteration count must be positive')
        .nullable()
        .optional()
        .describe(
            "For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule."
        ),
    iteration_frequency_days: z
        .number()
        .positive('Iteration frequency must be positive')
        .max(365, 'Iteration frequency cannot exceed 365 days')
        .nullable()
        .optional()
        .describe(
            'For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.'
        ),
    enable_partial_responses: z
        .boolean()
        .optional()
        .describe(
            'When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).'
        ),
    linked_flag_id: z.number().nullable().optional().describe('The feature flag to link to this survey'),
    targeting_flag_id: z.number().optional().describe('An existing targeting flag to use for this survey'),
    targeting_flag_filters: FilterGroupsSchema.optional().describe(
        "Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 50}]}"
    ),
    remove_targeting_flag: z
        .boolean()
        .optional()
        .describe(
            'Set to true to completely remove all targeting filters from the survey, making it visible to all users (subject to other display conditions like URL matching).'
        ),
})

export const ListSurveysInputSchema = z.object({
    limit: z.number().optional(),
    offset: z.number().optional(),
    search: z.string().optional(),
})

export const GetSurveyStatsInputSchema = z.object({
    date_from: z
        .string()
        .datetime()
        .optional()
        .describe('Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)'),
    date_to: z
        .string()
        .datetime()
        .optional()
        .describe('Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)'),
})

export const GetSurveySpecificStatsInputSchema = z.object({
    survey_id: z.string(),
    date_from: z
        .string()
        .datetime()
        .optional()
        .describe('Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)'),
    date_to: z
        .string()
        .datetime()
        .optional()
        .describe('Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)'),
})

// Input types
export type CreateSurveyInput = z.infer<typeof CreateSurveyInputSchema>
export type UpdateSurveyInput = z.infer<typeof UpdateSurveyInputSchema>
export type ListSurveysInput = z.infer<typeof ListSurveysInputSchema>
export type GetSurveyStatsInput = z.infer<typeof GetSurveyStatsInputSchema>
export type GetSurveySpecificStatsInput = z.infer<typeof GetSurveySpecificStatsInputSchema>
export type SurveyQuestionInput = z.infer<typeof SurveyQuestionInputSchema>

export interface SurveyEventStatsOutput {
    total_count?: number | null
    total_count_only_seen?: number | null
    unique_persons?: number | null
    unique_persons_only_seen?: number | null
    first_seen?: string | null
    last_seen?: string | null
}

export interface SurveyRatesOutput {
    response_rate?: number | null
    dismissal_rate?: number | null
    unique_users_response_rate?: number | null
    unique_users_dismissal_rate?: number | null
}

export interface SurveyResponseStatsOutput {
    survey_id?: string | null
    start_date?: string | null
    end_date?: string | null
    stats?: {
        'survey shown'?: SurveyEventStatsOutput | null
        'survey dismissed'?: SurveyEventStatsOutput | null
        'survey sent'?: SurveyEventStatsOutput | null
    } | null
    rates: {
        response_rate?: number | null
        dismissal_rate?: number | null
        unique_users_response_rate?: number | null
        unique_users_dismissal_rate?: number | null
    }
}
