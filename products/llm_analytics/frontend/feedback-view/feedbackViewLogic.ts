import { afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { LLMTraceEvent } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { Survey, SurveyEventProperties } from '~/types'

import type { feedbackViewLogicType } from './feedbackViewLogicType'

export interface FeedbackViewLogicProps {
    traceId: string
    traceCreatedAt: string | null
}

export const feedbackViewLogic = kea<feedbackViewLogicType>([
    path(['scenes', 'llm-analytics', 'feedbackViewLogic']),
    props({} as FeedbackViewLogicProps),
    key((props) => props.traceId),
    loaders(({ props, values }) => ({
        surveyEvents: [
            null as LLMTraceEvent[] | null,
            {
                loadSurveyEvents: async (createdAt: string) => {
                    const date = dayjs(createdAt)
                    const response = await api.queryHogQL(
                        hogql`
                            SELECT uuid, event, timestamp, properties
                            FROM events
                            WHERE (event = 'survey sent' OR event = 'survey shown')
                                AND properties.$ai_trace_id = ${props.traceId}
                                AND timestamp >= ${date}
                            ORDER BY if(event = 'survey sent', 0, 1)
                            LIMIT 1 BY properties.$survey_id
                        `,
                        { productKey: 'llm_analytics' }
                    )

                    return response.results.map(([uuid, event, timestamp, properties]: any) => ({
                        id: uuid,
                        event,
                        createdAt: timestamp,
                        properties: typeof properties === 'string' ? JSON.parse(properties) : properties,
                    }))
                },
            },
        ],
        surveys: [
            {} as Record<string, Survey>,
            {
                loadSurveys: async () => {
                    const surveyIds = values.surveyIds
                    if (surveyIds.length === 0) {
                        return {}
                    }
                    const surveys = await Promise.all(surveyIds.map((id) => api.surveys.get(id)))
                    return Object.fromEntries(surveys.map((survey) => [survey.id, survey]))
                },
            },
        ],
    })),
    reducers({
        hasLoadingError: [
            false,
            {
                loadSurveyEventsFailure: () => true,
                loadSurveysFailure: () => true,
                loadSurveyEvents: () => false,
            },
        ],
    }),
    selectors({
        surveyIds: [
            (s) => [s.surveyEvents],
            (surveyEvents): string[] => {
                if (!surveyEvents) {
                    return []
                }
                const ids = new Set<string>()
                for (const event of surveyEvents) {
                    const surveyId = event.properties?.[SurveyEventProperties.SURVEY_ID]
                    if (surveyId) {
                        ids.add(surveyId)
                    }
                }
                return Array.from(ids)
            },
        ],
    }),
    listeners(({ actions }) => ({
        loadSurveyEventsSuccess: () => {
            actions.loadSurveys()
        },
    })),
    afterMount(({ actions, values, props }) => {
        if (props.traceCreatedAt && values.surveyEvents === null && !values.surveyEventsLoading) {
            actions.loadSurveyEvents(props.traceCreatedAt)
        }
    }),
])
