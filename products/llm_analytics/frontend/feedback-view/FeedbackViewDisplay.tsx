import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SurveyEventProperties } from '~/types'

import { llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'
import { feedbackViewLogic } from './feedbackViewLogic'
import { SurveyResponseCard } from './survey-responses/SurveyResponseCard'
import { groupEventsBySubmission } from './survey-responses/utils'
import { FeedbackSurveyWizard } from './wizard/FeedbackSurveyWizard'

export function FeedbackViewDisplay(): JSX.Element {
    const { traceId } = useValues(llmAnalyticsTraceLogic)
    const { surveyEvents, surveyEventsLoading, surveys, surveysLoading, hasLoadingError } = useValues(
        feedbackViewLogic({ traceId })
    )
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    if (surveyEventsLoading || surveysLoading) {
        return <LemonSkeleton className="h-8" />
    }

    if (hasLoadingError) {
        return <LemonBanner type="error">Failed to load feedback data</LemonBanner>
    }

    const surveyResponseEvents = (surveyEvents ?? []).filter((e) => e.event === 'survey sent')
    const groupedResponses = groupEventsBySubmission(surveyResponseEvents, surveys)

    // survey events are deduped on survey_id (and implicitly trace_id), so we'll
    // only have 'survey shown' events here if there was no survey response
    const surveyShownEvents = (surveyEvents ?? []).filter((e) => e.event === 'survey shown')

    const hasSurveyEvents = groupedResponses.length > 0 || surveyShownEvents.length > 0

    // no survey events at all -> survey wizard CTA
    if (!hasSurveyEvents) {
        return <FeedbackSurveyWizard />
    }

    return (
        <div className="flex flex-col gap-3">
            {hasSurveyEvents && !currentTeam?.surveys_opt_in && (
                <LemonBanner type="warning">
                    <div className="flex items-center justify-between gap-2">
                        <span>Surveys are disabled for this project. Your feedback surveys won't work.</span>
                        <LemonSwitch
                            checked={false}
                            onChange={(checked) => updateCurrentTeam({ surveys_opt_in: checked })}
                            label="Enable surveys"
                            bordered
                        />
                    </div>
                </LemonBanner>
            )}

            {groupedResponses.map((response) => {
                const survey = surveys[response.surveyId]
                if (!survey) {
                    return null
                }
                return <SurveyResponseCard key={response.submissionId} response={response} survey={survey} />
            })}

            {surveyShownEvents.map((event) => {
                const survey = surveys[event.properties?.[SurveyEventProperties.SURVEY_ID]]
                return (
                    <LemonCard key={event.id} className="p-3" hoverEffect={false}>
                        <span className="text-secondary">
                            {survey ? (
                                <Link to={urls.survey(survey.id)} target="_blank" targetBlankIcon>
                                    {survey.name}
                                </Link>
                            ) : (
                                'Survey'
                            )}{' '}
                            was shown but received no response
                        </span>
                    </LemonCard>
                )
            })}
        </div>
    )
}
