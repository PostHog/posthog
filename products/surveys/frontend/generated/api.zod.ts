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

/**
 * Stores selected attachments and submits one response to the PostHog Desktop feedback survey.
 * @summary Submit Desktop feedback
 */
export const desktopFeedbackCreateBodyResponseMax = 4000

export const desktopFeedbackCreateBodyFeedbackViewMax = 100

export const desktopFeedbackCreateBodyFeedbackTaskIdMax = 100

export const desktopFeedbackCreateBodyFeedbackFolderIdMax = 100

export const desktopFeedbackCreateBodyFeedbackAppLogsMax = 20000

export const desktopFeedbackCreateBodyAppVersionMax = 100

export const DesktopFeedbackCreateBody = /* @__PURE__ */ zod.object({
    response: zod.string().max(desktopFeedbackCreateBodyResponseMax).describe('Feedback text entered by the user.'),
    source: zod
        .enum(['Generic (Leave feedback button)', 'Visiting PostHog web'])
        .describe('\* `Generic (Leave feedback button)` - Leave Feedback\n\* `Visiting PostHog web` - Posthog Web')
        .describe(
            'Desktop surface that opened the feedback form.\n\n\* `Generic (Leave feedback button)` - Leave Feedback\n\* `Visiting PostHog web` - Posthog Web'
        ),
    feedback_view: zod
        .string()
        .max(desktopFeedbackCreateBodyFeedbackViewMax)
        .describe('Desktop view that was active when the feedback form opened.'),
    feedback_type: zod
        .enum(['bug', 'feature', 'general'])
        .describe('\* `bug` - Bug\n\* `feature` - Feature\n\* `general` - General')
        .optional()
        .describe(
            'Feedback type selected by the user: bug, feature, or general.\n\n\* `bug` - Bug\n\* `feature` - Feature\n\* `general` - General'
        ),
    feedback_task_id: zod
        .string()
        .max(desktopFeedbackCreateBodyFeedbackTaskIdMax)
        .optional()
        .describe('Task that was active when the feedback form opened.'),
    feedback_folder_id: zod
        .string()
        .max(desktopFeedbackCreateBodyFeedbackFolderIdMax)
        .optional()
        .describe('Folder that was active when the feedback form opened.'),
    feedback_app_logs: zod
        .string()
        .max(desktopFeedbackCreateBodyFeedbackAppLogsMax)
        .optional()
        .describe('Recent Desktop logs that the user chose to include.'),
    app_version: zod
        .string()
        .max(desktopFeedbackCreateBodyAppVersionMax)
        .optional()
        .describe('Version of PostHog Desktop that submitted the feedback.'),
    session_id: zod.uuid().optional().describe('PostHog session recording identifier for the Desktop session.'),
    screenshot: zod.instanceof(File).optional().describe('Screenshot that the user chose to include.'),
    image_1: zod.instanceof(File).optional().describe('First image that the user attached.'),
    image_2: zod.instanceof(File).optional().describe('Second image that the user attached.'),
})

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const SurveysCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const SurveysUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const SurveysPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Duplicate a survey to multiple projects in a single transaction.
 *
 * Accepts a list of target team IDs and creates a copy of the survey in each project.
 * Every target project must be in the source project's organization, and the caller needs
 * survey editor access in each one.
 * Uses an all-or-nothing approach - if any duplication fails, all changes are rolled back.
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

export const surveysDuplicateToProjectsCreateBodyBaseLanguageMax = 20

export const SurveysDuplicateToProjectsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysDuplicateToProjectsCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe(
            '\* `popover` - popover\n\* `widget` - widget\n\* `external_survey` - external survey\n\* `api` - api'
        ),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
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
    start_date: zod.iso.datetime({ offset: true }).nullish(),
    end_date: zod.iso.datetime({ offset: true }).nullish(),
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
    iteration_start_dates: zod.array(zod.iso.datetime({ offset: true }).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysDuplicateToProjectsCreateBodyCurrentIterationMin)
        .max(surveysDuplicateToProjectsCreateBodyCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_interval_type: zod
        .union([
            zod.enum(['day', 'week', 'month']).describe('\* `day` - day\n\* `week` - week\n\* `month` - month'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
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
    response_sampling_daily_limits: zod.unknown().optional(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    base_language: zod
        .string()
        .max(surveysDuplicateToProjectsCreateBodyBaseLanguageMax)
        .optional()
        .describe(
            "BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`."
        ),
    translations: zod.unknown().optional(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().optional(),
})

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const surveysGenerateTranslationsCreateBodyOverwriteDefault = false

export const SurveysGenerateTranslationsCreateBody = /* @__PURE__ */ zod.object({
    target_language: zod.string().describe('Language code to generate translations for, for example pt-BR.'),
    source_language: zod
        .string()
        .optional()
        .describe(
            "Optional override for the source language code. Defaults to the survey's `base_language` (or 'en' if unset)."
        ),
    overwrite: zod
        .boolean()
        .default(surveysGenerateTranslationsCreateBodyOverwriteDefault)
        .describe('Whether to overwrite existing translations for this language.'),
    survey: zod
        .record(zod.string(), zod.unknown().describe('Draft survey field value.'))
        .optional()
        .describe('Optional translation-only draft survey payload to translate instead of the last saved survey.'),
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

export const surveysResponsesArchiveCreateBodyBaseLanguageMax = 20

export const SurveysResponsesArchiveCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysResponsesArchiveCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe(
            '\* `popover` - popover\n\* `widget` - widget\n\* `external_survey` - external survey\n\* `api` - api'
        ),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
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
    start_date: zod.iso.datetime({ offset: true }).nullish(),
    end_date: zod.iso.datetime({ offset: true }).nullish(),
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
    iteration_start_dates: zod.array(zod.iso.datetime({ offset: true }).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysResponsesArchiveCreateBodyCurrentIterationMin)
        .max(surveysResponsesArchiveCreateBodyCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_interval_type: zod
        .union([
            zod.enum(['day', 'week', 'month']).describe('\* `day` - day\n\* `week` - week\n\* `month` - month'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
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
    response_sampling_daily_limits: zod.unknown().optional(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    base_language: zod
        .string()
        .max(surveysResponsesArchiveCreateBodyBaseLanguageMax)
        .optional()
        .describe(
            "BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`."
        ),
    translations: zod.unknown().optional(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().optional(),
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

export const surveysResponsesUnarchiveCreateBodyBaseLanguageMax = 20

export const SurveysResponsesUnarchiveCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysResponsesUnarchiveCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe(
            '\* `popover` - popover\n\* `widget` - widget\n\* `external_survey` - external survey\n\* `api` - api'
        ),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
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
    start_date: zod.iso.datetime({ offset: true }).nullish(),
    end_date: zod.iso.datetime({ offset: true }).nullish(),
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
    iteration_start_dates: zod.array(zod.iso.datetime({ offset: true }).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysResponsesUnarchiveCreateBodyCurrentIterationMin)
        .max(surveysResponsesUnarchiveCreateBodyCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_interval_type: zod
        .union([
            zod.enum(['day', 'week', 'month']).describe('\* `day` - day\n\* `week` - week\n\* `month` - month'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
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
    response_sampling_daily_limits: zod.unknown().optional(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    base_language: zod
        .string()
        .max(surveysResponsesUnarchiveCreateBodyBaseLanguageMax)
        .optional()
        .describe(
            "BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`."
        ),
    translations: zod.unknown().optional(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().optional(),
})

/**
 * Summarize survey responses. When `question_index` or `question_id` is provided, returns a per-question theme summary using cached `survey.question_summaries` when fresh. When neither is provided, returns the survey-wide headline summary (delegates to summary_headline). Pass `force_refresh=true` in the body to bypass caches.
 */
export const surveysSummarizeResponsesCreateBodyForceRefreshDefault = false

export const SurveysSummarizeResponsesCreateBody = /* @__PURE__ */ zod.object({
    force_refresh: zod
        .boolean()
        .default(surveysSummarizeResponsesCreateBodyForceRefreshDefault)
        .describe('When true, bypass cached summaries and regenerate. Defaults to false.'),
})

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
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

export const surveysSummaryHeadlineCreateBodyBaseLanguageMax = 20

export const SurveysSummaryHeadlineCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(surveysSummaryHeadlineCreateBodyNameMax),
    description: zod.string().optional(),
    type: zod
        .enum(['popover', 'widget', 'external_survey', 'api'])
        .describe(
            '\* `popover` - popover\n\* `widget` - widget\n\* `external_survey` - external survey\n\* `api` - api'
        ),
    schedule: zod.string().nullish(),
    linked_flag_id: zod.number().nullish(),
    linked_insight_id: zod.number().nullish(),
    targeting_flag_id: zod.number().optional(),
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
    start_date: zod.iso.datetime({ offset: true }).nullish(),
    end_date: zod.iso.datetime({ offset: true }).nullish(),
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
    iteration_start_dates: zod.array(zod.iso.datetime({ offset: true }).nullable()).nullish(),
    current_iteration: zod
        .number()
        .min(surveysSummaryHeadlineCreateBodyCurrentIterationMin)
        .max(surveysSummaryHeadlineCreateBodyCurrentIterationMax)
        .nullish(),
    current_iteration_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_start_date: zod.iso.datetime({ offset: true }).nullish(),
    response_sampling_interval_type: zod
        .union([
            zod.enum(['day', 'week', 'month']).describe('\* `day` - day\n\* `week` - week\n\* `month` - month'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
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
    response_sampling_daily_limits: zod.unknown().optional(),
    enable_partial_responses: zod.boolean().nullish(),
    enable_iframe_embedding: zod.boolean().nullish(),
    base_language: zod
        .string()
        .max(surveysSummaryHeadlineCreateBodyBaseLanguageMax)
        .optional()
        .describe(
            "BCP-47 language code (e.g. 'en', 'es', 'es-MX') describing the language of the survey's untranslated text. Defaults to 'en'. Cannot also appear as a key in `translations`."
        ),
    translations: zod.unknown().optional(),
    _create_in_folder: zod.string().optional(),
    form_content: zod.unknown().optional(),
})
