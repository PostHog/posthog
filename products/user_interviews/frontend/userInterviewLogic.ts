import { kea, key, path, props, selectors } from 'kea'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { userInterviewLogicType } from './userInterviewLogicType'

export interface UserInterviewLogicProps {
    id: string
}

export const userInterviewLogic = kea<userInterviewLogicType>([
    path(['products', 'user_interviews', 'frontend', 'userInterviewLogic']),
    props({} as UserInterviewLogicProps),
    key((props) => props.id),
    selectors(({ props }) => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'UserInterviews',
                    name: 'User research',
                    path: urls.userInterviews(),
                    iconType: 'user_interview',
                },
                {
                    key: props.id,
                    name: props.id,
                    path: urls.userInterview(props.id),
                    iconType: 'user_interview',
                },
            ],
        ],
    })),
])
