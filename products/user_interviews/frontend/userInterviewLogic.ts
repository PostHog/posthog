import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    getUserInterviewTopicsLinksCsvCreateUrl,
    userInterviewTopicsGenerateLinksCreate,
    userInterviewTopicsIntervieweesList,
    userInterviewTopicsPreviewInviteCreate,
    userInterviewTopicsRetrieve,
    userInterviewTopicsTestLinkRetrieve,
    userInterviewsList,
} from './generated/api'
import type {
    IntervieweeContextApi,
    InterviewLinkApi,
    PreviewInviteResultApi,
    TestInterviewLinkApi,
    UserInterviewApi,
    UserInterviewTopicApi,
} from './generated/api.schemas'
import type { userInterviewLogicType } from './userInterviewLogicType'

export interface UserInterviewLogicProps {
    id: string
}

function unwrapPaginatedOrArray<T>(response: T[] | { results?: T[] }): T[] {
    if (Array.isArray(response)) {
        return response
    }
    return response.results ?? []
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
        links: {
            __default: [] as InterviewLinkApi[],
            loadLinks: async (): Promise<InterviewLinkApi[]> => {
                const projectId = String(teamLogic.values.currentTeamId)
                const response = (await userInterviewTopicsGenerateLinksCreate(projectId, props.id)) as unknown as
                    | InterviewLinkApi[]
                    | { results?: InterviewLinkApi[] }
                return unwrapPaginatedOrArray(response)
            },
        },
        testLink: {
            __default: null as TestInterviewLinkApi | null,
            loadTestLink: async (): Promise<TestInterviewLinkApi> => {
                const projectId = String(teamLogic.values.currentTeamId)
                return await userInterviewTopicsTestLinkRetrieve(projectId, props.id)
            },
        },
        invitePreview: {
            __default: null as PreviewInviteResultApi | null,
            loadInvitePreview: async (identifier: string): Promise<PreviewInviteResultApi> => {
                const projectId = String(teamLogic.values.currentTeamId)
                return await userInterviewTopicsPreviewInviteCreate(projectId, props.id, {
                    interviewee_identifier: identifier,
                })
            },
        },
    })),
    actions({
        exportLinksCsv: true,
        exportLinksCsvDone: true,
        openInvitePreview: (identifier: string) => ({ identifier }),
        closeInvitePreview: true,
    }),
    reducers({
        linksLoadFailed: [
            false,
            {
                loadLinks: () => false,
                loadLinksFailure: () => true,
            },
        ],
        linksCsvExporting: [
            false,
            {
                exportLinksCsv: () => true,
                exportLinksCsvDone: () => false,
            },
        ],
        previewInviteIdentifier: [
            null as string | null,
            {
                openInvitePreview: (_, { identifier }) => identifier,
                closeInvitePreview: () => null,
            },
        ],
    }),
    listeners(({ props, values, actions }) => ({
        openInvitePreview: ({ identifier }) => {
            actions.loadInvitePreview(identifier)
        },
        exportLinksCsv: async () => {
            const projectId = String(teamLogic.values.currentTeamId)
            try {
                const response = await api.createResponse(getUserInterviewTopicsLinksCsvCreateUrl(projectId, props.id))
                if (!response.ok) {
                    throw new Error(`Export failed (${response.status})`)
                }
                const blob = await response.blob()
                const filename = `${(values.topic?.topic || 'user-interview')
                    .replace(/[^\w-]+/g, '-')
                    .toLowerCase()}-links.csv`
                const url = URL.createObjectURL(blob)
                const anchor = document.createElement('a')
                anchor.href = url
                anchor.download = filename
                document.body.appendChild(anchor)
                anchor.click()
                document.body.removeChild(anchor)
                URL.revokeObjectURL(url)
            } catch {
                lemonToast.error('Could not export interview links as CSV')
            } finally {
                actions.exportLinksCsvDone()
            }
        },
    })),
    selectors(({ props }) => ({
        topicInterviews: [
            (s) => [s.interviews],
            (interviews): UserInterviewApi[] => interviews.filter((i) => i.topic === props.id),
        ],
        linkByIdentifier: [
            (s) => [s.links],
            (links): Record<string, string> =>
                Object.fromEntries(links.map((link) => [link.interviewee_identifier, link.interview_url])),
        ],
        linkForIdentifier: [
            (s) => [s.linkByIdentifier],
            (linkByIdentifier): ((identifier: string) => string | undefined) =>
                (identifier: string) =>
                    linkByIdentifier[identifier],
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
        actions.loadLinks()
        actions.loadTestLink()
    }),
])
