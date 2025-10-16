import type { SurveyListItemOutput, SurveyOutput } from '@/schema/surveys'
import type { Context } from '@/tools/types'

type SurveyData = SurveyOutput | SurveyListItemOutput

export interface FormattedSurvey extends Omit<SurveyData, 'end_date'> {
    status: 'draft' | 'active' | 'completed' | 'archived'
    end_date?: string | undefined
    url?: string
}

/**
 * Formats a survey with consistent status logic and additional fields
 */
export function formatSurvey(
    survey: SurveyData,
    context: Context,
    projectId: string
): FormattedSurvey {
    const status = survey.archived
        ? 'archived'
        : survey.start_date === null || survey.start_date === undefined
          ? 'draft'
          : survey.end_date
            ? 'completed'
            : 'active'

    const formatted: FormattedSurvey = {
        ...survey,
        status,
        end_date: survey.end_date || undefined, // Don't show null end_date
    }

    // Add URL if we have context and survey ID
    if (context && survey.id && projectId) {
        const baseUrl = context.api.getProjectBaseUrl(projectId)
        formatted.url = `${baseUrl}/surveys/${survey.id}`
    }

    return formatted
}

/**
 * Formats multiple surveys consistently
 */
export function formatSurveys(
    surveys: SurveyData[],
    context: Context,
    projectId: string
): FormattedSurvey[] {
    return surveys.map((survey) => formatSurvey(survey, context, projectId))
}
