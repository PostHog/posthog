import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { userInterviewTopicsList, userInterviewsSearchCreate } from './generated/api'
import type { UserInterviewSearchResultApi, UserInterviewTopicApi } from './generated/api.schemas'
import type { userInterviewsLogicType } from './userInterviewsLogicType'

export const userInterviewsLogic = kea<userInterviewsLogicType>([
    path(['products', 'user_interviews', 'frontend', 'userInterviewsLogic']),
    actions({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
    }),
    reducers({
        searchQuery: [
            '' as string,
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
    }),
    loaders(({ values }) => ({
        topics: {
            __default: [] as UserInterviewTopicApi[],
            loadTopics: async () => {
                const projectId = String(teamLogic.values.currentTeamId)
                const response = await userInterviewTopicsList(projectId)
                return response.results
            },
        },
        searchResults: {
            __default: [] as UserInterviewSearchResultApi[],
            loadSearchResults: async (_: unknown, breakpoint) => {
                await breakpoint(300)
                const query = values.searchQuery.trim()
                if (!query) {
                    return []
                }
                const projectId = String(teamLogic.values.currentTeamId)
                const results = await userInterviewsSearchCreate(projectId, { query })
                breakpoint()
                return results
            },
        },
    })),
    listeners(({ actions }) => ({
        setSearchQuery: () => {
            actions.loadSearchResults(null)
        },
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'UserInterviews',
                    name: 'User research',
                    path: urls.userInterviews(),
                    iconType: 'user_interview',
                },
            ],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadTopics()
    }),
])
