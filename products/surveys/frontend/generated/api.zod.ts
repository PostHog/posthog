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

export const SurveysCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const surveysUpdateBodyNameMax = 400

export const surveysUpdateBodyResponsesLimitMin = 0
export const surveysUpdateBodyResponsesLimitMax = 2147483647

export const surveysUpdateBodyIterationCountMin = 0
export const surveysUpdateBodyIterationCountMax = 500

export const surveysUpdateBodyIterationFrequencyDaysMin = 0
export const surveysUpdateBodyIterationFrequencyDaysMax = 2147483647

export const surveysUpdateBodyCurrentIterationMin = 0
export const surveysUpdateBodyCurrentIterationMax = 2147483647

export const surveysUpdateBodyResponseSamplingIntervalMin = 0
export const surveysUpdateBodyResponseSamplingIntervalMax = 2147483647

export const surveysUpdateBodyResponseSamplingLimitMin = 0
export const surveysUpdateBodyResponseSamplingLimitMax = 2147483647

export const SurveysUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(surveysUpdateBodyNameMax),
        description: zod.string().optional(),
        type: zod
            .enum(['popover', 'widget', 'external_survey', 'api'])
            .describe(
                '* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api'
            ),
        schedule: zod.string().nullish(),
        linked_flag_id: zod.number().nullish(),
        linked_insight_id: zod.number().nullish(),
        questions: zod
            .unknown()
            .nullish()
            .describe(
                '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Any string - allows customers to use their own language keys (e.g., \"es\", \"es-MX\", \"english\", \"french\")\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
            ),
        appearance: zod.unknown().nullish(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        responses_limit: zod
            .number()
            .min(surveysUpdateBodyResponsesLimitMin)
            .max(surveysUpdateBodyResponsesLimitMax)
            .nullish(),
        iteration_count: zod
            .number()
            .min(surveysUpdateBodyIterationCountMin)
            .max(surveysUpdateBodyIterationCountMax)
            .nullish(),
        iteration_frequency_days: zod
            .number()
            .min(surveysUpdateBodyIterationFrequencyDaysMin)
            .max(surveysUpdateBodyIterationFrequencyDaysMax)
            .nullish(),
        iteration_start_dates: zod.array(zod.iso.datetime({}).nullable()).nullish(),
        current_iteration: zod
            .number()
            .min(surveysUpdateBodyCurrentIterationMin)
            .max(surveysUpdateBodyCurrentIterationMax)
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
            .min(surveysUpdateBodyResponseSamplingIntervalMin)
            .max(surveysUpdateBodyResponseSamplingIntervalMax)
            .nullish(),
        response_sampling_limit: zod
            .number()
            .min(surveysUpdateBodyResponseSamplingLimitMin)
            .max(surveysUpdateBodyResponseSamplingLimitMax)
            .nullish(),
        response_sampling_daily_limits: zod.unknown().nullish(),
        enable_partial_responses: zod.boolean().nullish(),
        enable_iframe_embedding: zod.boolean().nullish(),
        translations: zod.unknown().nullish(),
        form_content: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const SurveysPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Duplicate a survey to multiple projects in a single transaction.

Accepts a list of target team IDs and creates a copy of the survey in each project.
Uses an all-or-nothing approach - if any duplication fails, all changes are rolled back.
 */
export const surveysDuplicateToProjectsCreateBodyNameMax = 400

export const surveysDuplicateToProjectsCreateBodyResponsesLimitMin = 0
export const surveysDuplicateToProjectsCreateBodyResponsesLimitMax = 2147483647

export const surveysDuplicateToProjectsCreateBodyIterationCountMin = 0
export const surveysDuplicateToProjectsCreateBodyIterationCountMax = 500

export const surveysDuplicateToProjectsCreateBodyIterationFrequencyDaysMin = 0
export const surveysDuplicateToProjectsCreateBodyIterationFrequencyDaysMax = 2147483647

export const surveysDuplicateToProjectsCreateBodyCurrentIterationMin = 0
export const surveysDuplicateToProjectsCreateBodyCurrentIterationMax = 2147483647

export const surveysDuplicateToProjectsCreateBodyResponseSamplingIntervalMin = 0
export const surveysDuplicateToProjectsCreateBodyResponseSamplingIntervalMax = 2147483647

export const surveysDuplicateToProjectsCreateBodyResponseSamplingLimitMin = 0
export const surveysDuplicateToProjectsCreateBodyResponseSamplingLimitMax = 2147483647

export const SurveysDuplicateToProjectsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysDuplicateToProjectsCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe('* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api'),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
    targeting_flag_filters: zod.unknown().nullish(),
    remove_targeting_flag: zod.boolean().nullish(),
    questions: zod
        .unknown()
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Any string - allows customers to use their own language keys (e.g., \"es\", \"es-MX\", \"english\", \"french\")\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod.unknown().nullish(),
    appearance: zod.unknown().nullish(),
    start_date: zod.iso.datetime({}).nullish(),
    end_date: zod.iso.datetime({}).nullish(),
    archived: zod.boolean().optional(),
    responses_limit: zod
        .number()
        .min(surveysDuplicateToProjectsCreateBodyResponsesLimitMin)
        .max(surveysDuplicateToProjectsCreateBodyResponsesLimitMax)
        .nullish(),
    iteration_count: zod
        .number()
        .min(surveysDuplicateToProjectsCreateBodyIterationCountMin)
        .max(surveysDuplicateToProjectsCreateBodyIterationCountMax)
        .nullish(),
    iteration_frequency_days: zod
        .number()
        .min(surveysDuplicateToProjectsCreateBodyIterationFrequencyDaysMin)
        .max(surveysDuplicateToProjectsCreateBodyIterationFrequencyDaysMax)
        .nullish(),
    iteration_start_dates: zod.array(zod.iso.datetime({}).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysDuplicateToProjectsCreateBodyCurrentIterationMin)
        .max(surveysDuplicateToProjectsCreateBodyCurrentIterationMax)
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
        .min(surveysDuplicateToProjectsCreateBodyResponseSamplingIntervalMin)
        .max(surveysDuplicateToProjectsCreateBodyResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveysDuplicateToProjectsCreateBodyResponseSamplingLimitMin)
        .max(surveysDuplicateToProjectsCreateBodyResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().nullish(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    translations: zod.unknown().nullish(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().nullish(),
})

/**
 * Archive a single survey response.
 */
export const surveysResponsesArchiveCreateBodyNameMax = 400

export const surveysResponsesArchiveCreateBodyResponsesLimitMin = 0
export const surveysResponsesArchiveCreateBodyResponsesLimitMax = 2147483647

export const surveysResponsesArchiveCreateBodyIterationCountMin = 0
export const surveysResponsesArchiveCreateBodyIterationCountMax = 500

export const surveysResponsesArchiveCreateBodyIterationFrequencyDaysMin = 0
export const surveysResponsesArchiveCreateBodyIterationFrequencyDaysMax = 2147483647

export const surveysResponsesArchiveCreateBodyCurrentIterationMin = 0
export const surveysResponsesArchiveCreateBodyCurrentIterationMax = 2147483647

export const surveysResponsesArchiveCreateBodyResponseSamplingIntervalMin = 0
export const surveysResponsesArchiveCreateBodyResponseSamplingIntervalMax = 2147483647

export const surveysResponsesArchiveCreateBodyResponseSamplingLimitMin = 0
export const surveysResponsesArchiveCreateBodyResponseSamplingLimitMax = 2147483647

export const SurveysResponsesArchiveCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysResponsesArchiveCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe('* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api'),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
    targeting_flag_filters: zod.unknown().nullish(),
    remove_targeting_flag: zod.boolean().nullish(),
    questions: zod
        .unknown()
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Any string - allows customers to use their own language keys (e.g., \"es\", \"es-MX\", \"english\", \"french\")\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod.unknown().nullish(),
    appearance: zod.unknown().nullish(),
    start_date: zod.iso.datetime({}).nullish(),
    end_date: zod.iso.datetime({}).nullish(),
    archived: zod.boolean().optional(),
    responses_limit: zod
        .number()
        .min(surveysResponsesArchiveCreateBodyResponsesLimitMin)
        .max(surveysResponsesArchiveCreateBodyResponsesLimitMax)
        .nullish(),
    iteration_count: zod
        .number()
        .min(surveysResponsesArchiveCreateBodyIterationCountMin)
        .max(surveysResponsesArchiveCreateBodyIterationCountMax)
        .nullish(),
    iteration_frequency_days: zod
        .number()
        .min(surveysResponsesArchiveCreateBodyIterationFrequencyDaysMin)
        .max(surveysResponsesArchiveCreateBodyIterationFrequencyDaysMax)
        .nullish(),
    iteration_start_dates: zod.array(zod.iso.datetime({}).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysResponsesArchiveCreateBodyCurrentIterationMin)
        .max(surveysResponsesArchiveCreateBodyCurrentIterationMax)
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
        .min(surveysResponsesArchiveCreateBodyResponseSamplingIntervalMin)
        .max(surveysResponsesArchiveCreateBodyResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveysResponsesArchiveCreateBodyResponseSamplingLimitMin)
        .max(surveysResponsesArchiveCreateBodyResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().nullish(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    translations: zod.unknown().nullish(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().nullish(),
})

/**
 * Unarchive a single survey response.
 */
export const surveysResponsesUnarchiveCreateBodyNameMax = 400

export const surveysResponsesUnarchiveCreateBodyResponsesLimitMin = 0
export const surveysResponsesUnarchiveCreateBodyResponsesLimitMax = 2147483647

export const surveysResponsesUnarchiveCreateBodyIterationCountMin = 0
export const surveysResponsesUnarchiveCreateBodyIterationCountMax = 500

export const surveysResponsesUnarchiveCreateBodyIterationFrequencyDaysMin = 0
export const surveysResponsesUnarchiveCreateBodyIterationFrequencyDaysMax = 2147483647

export const surveysResponsesUnarchiveCreateBodyCurrentIterationMin = 0
export const surveysResponsesUnarchiveCreateBodyCurrentIterationMax = 2147483647

export const surveysResponsesUnarchiveCreateBodyResponseSamplingIntervalMin = 0
export const surveysResponsesUnarchiveCreateBodyResponseSamplingIntervalMax = 2147483647

export const surveysResponsesUnarchiveCreateBodyResponseSamplingLimitMin = 0
export const surveysResponsesUnarchiveCreateBodyResponseSamplingLimitMax = 2147483647

export const SurveysResponsesUnarchiveCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysResponsesUnarchiveCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe('* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api'),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
    targeting_flag_filters: zod.unknown().nullish(),
    remove_targeting_flag: zod.boolean().nullish(),
    questions: zod
        .unknown()
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Any string - allows customers to use their own language keys (e.g., \"es\", \"es-MX\", \"english\", \"french\")\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod.unknown().nullish(),
    appearance: zod.unknown().nullish(),
    start_date: zod.iso.datetime({}).nullish(),
    end_date: zod.iso.datetime({}).nullish(),
    archived: zod.boolean().optional(),
    responses_limit: zod
        .number()
        .min(surveysResponsesUnarchiveCreateBodyResponsesLimitMin)
        .max(surveysResponsesUnarchiveCreateBodyResponsesLimitMax)
        .nullish(),
    iteration_count: zod
        .number()
        .min(surveysResponsesUnarchiveCreateBodyIterationCountMin)
        .max(surveysResponsesUnarchiveCreateBodyIterationCountMax)
        .nullish(),
    iteration_frequency_days: zod
        .number()
        .min(surveysResponsesUnarchiveCreateBodyIterationFrequencyDaysMin)
        .max(surveysResponsesUnarchiveCreateBodyIterationFrequencyDaysMax)
        .nullish(),
    iteration_start_dates: zod.array(zod.iso.datetime({}).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysResponsesUnarchiveCreateBodyCurrentIterationMin)
        .max(surveysResponsesUnarchiveCreateBodyCurrentIterationMax)
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
        .min(surveysResponsesUnarchiveCreateBodyResponseSamplingIntervalMin)
        .max(surveysResponsesUnarchiveCreateBodyResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveysResponsesUnarchiveCreateBodyResponseSamplingLimitMin)
        .max(surveysResponsesUnarchiveCreateBodyResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().nullish(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    translations: zod.unknown().nullish(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().nullish(),
})

export const surveysSummarizeResponsesCreateBodyNameMax = 400

export const surveysSummarizeResponsesCreateBodyResponsesLimitMin = 0
export const surveysSummarizeResponsesCreateBodyResponsesLimitMax = 2147483647

export const surveysSummarizeResponsesCreateBodyIterationCountMin = 0
export const surveysSummarizeResponsesCreateBodyIterationCountMax = 500

export const surveysSummarizeResponsesCreateBodyIterationFrequencyDaysMin = 0
export const surveysSummarizeResponsesCreateBodyIterationFrequencyDaysMax = 2147483647

export const surveysSummarizeResponsesCreateBodyCurrentIterationMin = 0
export const surveysSummarizeResponsesCreateBodyCurrentIterationMax = 2147483647

export const surveysSummarizeResponsesCreateBodyResponseSamplingIntervalMin = 0
export const surveysSummarizeResponsesCreateBodyResponseSamplingIntervalMax = 2147483647

export const surveysSummarizeResponsesCreateBodyResponseSamplingLimitMin = 0
export const surveysSummarizeResponsesCreateBodyResponseSamplingLimitMax = 2147483647

export const SurveysSummarizeResponsesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysSummarizeResponsesCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe('* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api'),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
    targeting_flag_filters: zod.unknown().nullish(),
    remove_targeting_flag: zod.boolean().nullish(),
    questions: zod
        .unknown()
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Any string - allows customers to use their own language keys (e.g., \"es\", \"es-MX\", \"english\", \"french\")\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod.unknown().nullish(),
    appearance: zod.unknown().nullish(),
    start_date: zod.iso.datetime({}).nullish(),
    end_date: zod.iso.datetime({}).nullish(),
    archived: zod.boolean().optional(),
    responses_limit: zod
        .number()
        .min(surveysSummarizeResponsesCreateBodyResponsesLimitMin)
        .max(surveysSummarizeResponsesCreateBodyResponsesLimitMax)
        .nullish(),
    iteration_count: zod
        .number()
        .min(surveysSummarizeResponsesCreateBodyIterationCountMin)
        .max(surveysSummarizeResponsesCreateBodyIterationCountMax)
        .nullish(),
    iteration_frequency_days: zod
        .number()
        .min(surveysSummarizeResponsesCreateBodyIterationFrequencyDaysMin)
        .max(surveysSummarizeResponsesCreateBodyIterationFrequencyDaysMax)
        .nullish(),
    iteration_start_dates: zod.array(zod.iso.datetime({}).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysSummarizeResponsesCreateBodyCurrentIterationMin)
        .max(surveysSummarizeResponsesCreateBodyCurrentIterationMax)
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
        .min(surveysSummarizeResponsesCreateBodyResponseSamplingIntervalMin)
        .max(surveysSummarizeResponsesCreateBodyResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveysSummarizeResponsesCreateBodyResponseSamplingLimitMin)
        .max(surveysSummarizeResponsesCreateBodyResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().nullish(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    translations: zod.unknown().nullish(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().nullish(),
})

export const surveysSummaryHeadlineCreateBodyNameMax = 400

export const surveysSummaryHeadlineCreateBodyResponsesLimitMin = 0
export const surveysSummaryHeadlineCreateBodyResponsesLimitMax = 2147483647

export const surveysSummaryHeadlineCreateBodyIterationCountMin = 0
export const surveysSummaryHeadlineCreateBodyIterationCountMax = 500

export const surveysSummaryHeadlineCreateBodyIterationFrequencyDaysMin = 0
export const surveysSummaryHeadlineCreateBodyIterationFrequencyDaysMax = 2147483647

export const surveysSummaryHeadlineCreateBodyCurrentIterationMin = 0
export const surveysSummaryHeadlineCreateBodyCurrentIterationMax = 2147483647

export const surveysSummaryHeadlineCreateBodyResponseSamplingIntervalMin = 0
export const surveysSummaryHeadlineCreateBodyResponseSamplingIntervalMax = 2147483647

export const surveysSummaryHeadlineCreateBodyResponseSamplingLimitMin = 0
export const surveysSummaryHeadlineCreateBodyResponseSamplingLimitMax = 2147483647

export const SurveysSummaryHeadlineCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysSummaryHeadlineCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe('* `popover` - popover\n* `widget` - widget\n* `external_survey` - external survey\n* `api` - api'),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
    targeting_flag_filters: zod.unknown().nullish(),
    remove_targeting_flag: zod.boolean().nullish(),
    questions: zod
        .unknown()
        .nullish()
        .describe(
            '\n        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.\n\n        Basic (open-ended question)\n        - `id`: The question ID\n        - `type`: `open`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Link (a question with a link)\n        - `id`: The question ID\n        - `type`: `link`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `link`: The URL associated with the question.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Rating (a question with a rating scale)\n        - `id`: The question ID\n        - `type`: `rating`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `display`: Display style of the rating (`number` or `emoji`).\n        - `scale`: The scale of the rating (`number`).\n        - `lowerBoundLabel`: Label for the lower bound of the scale.\n        - `upperBoundLabel`: Label for the upper bound of the scale.\n        - `isNpsQuestion`: Whether the question is an NPS rating.\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Multiple choice\n        - `id`: The question ID\n        - `type`: `single_choice` or `multiple_choice`\n        - `question`: The text of the question.\n        - `description`: Optional description of the question.\n        - `descriptionContentType`: Content type of the description (`html` or `text`).\n        - `optional`: Whether the question is optional (`boolean`).\n        - `buttonText`: Text displayed on the submit button.\n        - `choices`: An array of choices for the question.\n        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).\n        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).\n        - `branching`: Branching logic for the question. See branching types below for details.\n\n        Branching logic can be one of the following types:\n\n        Next question: Proceeds to the next question\n        ```json\n        {\n            \"type\": \"next_question\"\n        }\n        ```\n\n        End: Ends the survey, optionally displaying a confirmation message.\n        ```json\n        {\n            \"type\": \"end\"\n        }\n        ```\n\n        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.\n        ```json\n        {\n            \"type\": \"response_based\",\n            \"responseValues\": {\n                \"responseKey\": \"value\"\n            }\n        }\n        ```\n\n        Specific question: Proceeds to a specific question by index.\n        ```json\n        {\n            \"type\": \"specific_question\",\n            \"index\": 2\n        }\n        ```\n\n        Translations: Each question can include inline translations.\n        - `translations`: Object mapping language codes to translated fields.\n        - Language codes: Any string - allows customers to use their own language keys (e.g., \"es\", \"es-MX\", \"english\", \"french\")\n        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`\n\n        Example with translations:\n        ```json\n        {\n            \"id\": \"uuid\",\n            \"type\": \"rating\",\n            \"question\": \"How satisfied are you?\",\n            \"lowerBoundLabel\": \"Not satisfied\",\n            \"upperBoundLabel\": \"Very satisfied\",\n            \"translations\": {\n                \"es\": {\n                    \"question\": \"¿Qué tan satisfecho estás?\",\n                    \"lowerBoundLabel\": \"No satisfecho\",\n                    \"upperBoundLabel\": \"Muy satisfecho\"\n                },\n                \"fr\": {\n                    \"question\": \"Dans quelle mesure êtes-vous satisfait?\"\n                }\n            }\n        }\n        ```\n        '
        ),
    conditions: zod.unknown().nullish(),
    appearance: zod.unknown().nullish(),
    start_date: zod.iso.datetime({}).nullish(),
    end_date: zod.iso.datetime({}).nullish(),
    archived: zod.boolean().optional(),
    responses_limit: zod
        .number()
        .min(surveysSummaryHeadlineCreateBodyResponsesLimitMin)
        .max(surveysSummaryHeadlineCreateBodyResponsesLimitMax)
        .nullish(),
    iteration_count: zod
        .number()
        .min(surveysSummaryHeadlineCreateBodyIterationCountMin)
        .max(surveysSummaryHeadlineCreateBodyIterationCountMax)
        .nullish(),
    iteration_frequency_days: zod
        .number()
        .min(surveysSummaryHeadlineCreateBodyIterationFrequencyDaysMin)
        .max(surveysSummaryHeadlineCreateBodyIterationFrequencyDaysMax)
        .nullish(),
    iteration_start_dates: zod.array(zod.iso.datetime({}).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysSummaryHeadlineCreateBodyCurrentIterationMin)
        .max(surveysSummaryHeadlineCreateBodyCurrentIterationMax)
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
        .min(surveysSummaryHeadlineCreateBodyResponseSamplingIntervalMin)
        .max(surveysSummaryHeadlineCreateBodyResponseSamplingIntervalMax)
        .nullish(),
    response_sampling_limit: zod
        .number()
        .min(surveysSummaryHeadlineCreateBodyResponseSamplingLimitMin)
        .max(surveysSummaryHeadlineCreateBodyResponseSamplingLimitMax)
        .nullish(),
    response_sampling_daily_limits: zod.unknown().nullish(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    translations: zod.unknown().nullish(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().nullish(),
})
