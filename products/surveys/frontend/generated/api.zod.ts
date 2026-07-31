/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    GenerateSurveyTranslationsRequestApi,
    PatchedSurveySerializerCreateUpdateOnlySchemaApi,
    SurveyApi,
    SurveySerializerCreateUpdateOnlyApi,
    SurveySerializerCreateUpdateOnlySchemaApi,
    SurveySummarizeRequestApi,
} from './api.zod.schemas'

export const SurveysCreateBody = SurveySerializerCreateUpdateOnlySchemaApi

export const SurveysUpdateBody = SurveyApi

export const SurveysPartialUpdateBody = PatchedSurveySerializerCreateUpdateOnlySchemaApi

/**
 * Duplicate a survey to multiple projects in a single transaction.
 *
 * Accepts a list of target team IDs and creates a copy of the survey in each project.
 * Uses an all-or-nothing approach - if any duplication fails, all changes are rolled back.
 */
export const SurveysDuplicateToProjectsCreateBody = SurveySerializerCreateUpdateOnlyApi

export const SurveysGenerateTranslationsCreateBody = GenerateSurveyTranslationsRequestApi

/**
 * Archive a single survey response.
 */
export const SurveysResponsesArchiveCreateBody = SurveySerializerCreateUpdateOnlyApi

/**
 * Unarchive a single survey response.
 */
export const SurveysResponsesUnarchiveCreateBody = SurveySerializerCreateUpdateOnlyApi

/**
 * Summarize survey responses. When `question_index` or `question_id` is provided, returns a per-question theme summary using cached `survey.question_summaries` when fresh. When neither is provided, returns the survey-wide headline summary (delegates to summary_headline). Pass `force_refresh=true` in the body to bypass caches.
 */
export const SurveysSummarizeResponsesCreateBody = SurveySummarizeRequestApi

export const SurveysSummaryHeadlineCreateBody = SurveySerializerCreateUpdateOnlyApi
