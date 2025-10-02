import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb, UserInterviewType } from '~/types'

import type { userInterviewsLogicType } from './userInterviewsLogicType'

export const userInterviewsLogic = kea<userInterviewsLogicType>([
    path(['products', 'user_interviews', 'frontend', 'userInterviewsLogic']),
    loaders({
        userInterviews: {
            __default: [] as UserInterviewType[],
            loadUserInterviews: async () => {
                const response = await api.userInterviews.list()
                return response.results
            },
        },
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'UserInterviews',
                    name: 'User interviews',
                    path: urls.userInterviews(),
                    iconType: 'user_interview',
                },
            ],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadUserInterviews()
    }),
])
