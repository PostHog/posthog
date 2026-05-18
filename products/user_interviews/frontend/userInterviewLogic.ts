import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    userInterviewTopicsAddIntervieweeCreate,
    userInterviewTopicsGenerateLinksCreate,
    userInterviewTopicsIntervieweesList,
    userInterviewTopicsRetrieve,
    userInterviewsList,
} from './generated/api'
import type {
    IntervieweeContextApi,
    InterviewLinkApi,
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
    actions({
        openAddPeopleModal: true,
        closeAddPeopleModal: true,
        addPeople: (emails: string[], distinctIds: string[]) => ({ emails, distinctIds }),
    }),
    reducers({
        addPeopleModalOpen: [
            false,
            {
                openAddPeopleModal: () => true,
                closeAddPeopleModal: () => false,
            },
        ],
        addingPeople: [
            false,
            {
                addPeople: () => true,
                closeAddPeopleModal: () => false,
            },
        ],
    }),
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
    })),
    reducers({
        linksLoadFailed: [
            false,
            {
                loadLinks: () => false,
                loadLinksFailure: () => true,
            },
        ],
    }),
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
    listeners(({ actions, props }) => ({
        addPeople: async ({ emails, distinctIds }) => {
            const projectId = String(teamLogic.values.currentTeamId)
            const identifiers = [...emails, ...distinctIds]
            // Upstream's `add_interviewee` endpoint takes one identifier at a time and
            // auto-routes emails vs distinct IDs based on validation. Fan out in parallel
            // and surface any per-identifier failures without aborting the whole batch.
            const results = await Promise.allSettled(
                identifiers.map((identifier) =>
                    userInterviewTopicsAddIntervieweeCreate(projectId, props.id, { identifier })
                )
            )
            const failed = results
                .map((result, i) => ({ result, identifier: identifiers[i] }))
                .filter(({ result }) => result.status === 'rejected')

            actions.closeAddPeopleModal()

            const succeeded = identifiers.length - failed.length
            if (succeeded > 0) {
                lemonToast.success(`Added ${succeeded} ${succeeded === 1 ? 'person' : 'people'} to this topic`)
            }
            if (failed.length > 0) {
                lemonToast.error(`Failed to add ${failed.length}: ${failed.map((f) => f.identifier).join(', ')}`)
            }

            actions.loadTopic()
            actions.loadInterviewees()
            actions.loadLinks()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTopic()
        actions.loadInterviewees()
        actions.loadInterviews()
        actions.loadLinks()
    }),
])
