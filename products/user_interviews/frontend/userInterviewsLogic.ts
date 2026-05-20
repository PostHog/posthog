import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { userInterviewTopicsList } from './generated/api'
import type { UserInterviewTopicApi } from './generated/api.schemas'
import type { userInterviewsLogicType } from './userInterviewsLogicType'

export const userInterviewsLogic = kea<userInterviewsLogicType>([
    path(['products', 'user_interviews', 'frontend', 'userInterviewsLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags', 'receivedFeatureFlags']],
    })),
    loaders({
        topics: {
            __default: [] as UserInterviewTopicApi[],
            loadTopics: async () => {
                const projectId = String(teamLogic.values.currentTeamId)
                try {
                    const response = await userInterviewTopicsList(projectId)
                    return response.results
                } catch {
                    return []
                }
            },
        },
    }),
    selectors({
        featureEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.USER_INTERVIEWS],
        ],
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
