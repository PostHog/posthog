import { afterMount, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { userInterviewTopicsRetrieve, userInterviewTopicsIntervieweesList, userInterviewsList } from './generated/api'
import type { UserInterviewTopicApi, IntervieweeContextApi, UserInterviewApi } from './generated/api.schemas'
import type { userInterviewLogicType } from './userInterviewLogicType'

export interface UserInterviewLogicProps {
    id: string
}

export const userInterviewLogic = kea<userInterviewLogicType>([
    path(['products', 'user_interviews', 'frontend', 'userInterviewLogic']),
    props({} as UserInterviewLogicProps),
    key((props) => props.id),
    loaders(({ props }) => ({
        topic: {
            __default: null as UserInterviewTopicApi | null,
            loadTopic: async () => {
                const projectId = String(teamLogic.values.currentTeamId)
                try {
                    return await userInterviewTopicsRetrieve(projectId, props.id)
                } catch {
                    return null
                }
            },
        },
        interviewees: {
            __default: [] as IntervieweeContextApi[],
            loadInterviewees: async () => {
                const projectId = String(teamLogic.values.currentTeamId)
                try {
                    const response = await userInterviewTopicsIntervieweesList(projectId, props.id)
                    return response.results
                } catch {
                    return []
                }
            },
        },
        interviews: {
            __default: [] as UserInterviewApi[],
            loadInterviews: async () => {
                const projectId = String(teamLogic.values.currentTeamId)
                try {
                    const response = await userInterviewsList(projectId)
                    return response.results
                } catch {
                    return []
                }
            },
        },
    })),
    selectors(({ props }) => ({
        topicInterviews: [
            (s) => [s.interviews],
            (interviews): UserInterviewApi[] => interviews.filter((i) => i.topic === props.id),
        ],
        respondedIdentifiers: [
            (s) => [s.topicInterviews],
            (interviews): Set<string> => {
                const responded = new Set<string>()
                for (const interview of interviews) {
                    if (interview.transcript || interview.summary) {
                        if (interview.interviewee_identifier) {
                            responded.add(interview.interviewee_identifier)
                        }
                    }
                }
                return responded
            },
        ],
        respondedCount: [
            (s) => [s.topic, s.respondedIdentifiers],
            (topic, respondedIdentifiers): number => {
                const allTargeted = [...(topic?.interviewee_emails || []), ...(topic?.interviewee_distinct_ids || [])]
                return allTargeted.filter((id) => respondedIdentifiers.has(id)).length
            },
        ],
        totalTargeted: [
            (s) => [s.topic],
            (topic): number =>
                (topic?.interviewee_emails?.length || 0) + (topic?.interviewee_distinct_ids?.length || 0),
        ],
        responseRate: [
            (s) => [s.respondedCount, s.totalTargeted],
            (respondedCount, totalTargeted): number =>
                totalTargeted > 0 ? Math.round((respondedCount / totalTargeted) * 100) : 0,
        ],
        breadcrumbs: [
            (s) => [s.topic],
            (topic): Breadcrumb[] => [
                {
                    key: 'UserInterviews',
                    name: 'User research',
                    path: urls.userInterviews(),
                    iconType: 'user_interview',
                },
                {
                    key: props.id,
                    name: topic?.topic || props.id,
                    path: urls.userInterview(props.id),
                    iconType: 'user_interview',
                },
            ],
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadTopic()
        actions.loadInterviewees()
        actions.loadInterviews()
    }),
])
