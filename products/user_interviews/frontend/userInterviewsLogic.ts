import { kea, path, selectors } from 'kea'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { userInterviewsLogicType } from './userInterviewsLogicType'

export const userInterviewsLogic = kea<userInterviewsLogicType>([
    path(['products', 'user_interviews', 'frontend', 'userInterviewsLogic']),
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
])
