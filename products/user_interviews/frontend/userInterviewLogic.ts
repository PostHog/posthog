import { afterMount, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb, UserInterviewType } from '~/types'

import type { userInterviewLogicType } from './userInterviewLogicType'
import { userInterviewsLogic } from './userInterviewsLogic'

export interface UserInterviewLogicProps {
    id: string
}

export const userInterviewLogic = kea<userInterviewLogicType>([
    path(['products', 'user_interviews', 'frontend', 'userInterviewLogic']),
    props({} as UserInterviewLogicProps),
    key((props) => props.id),
    loaders(({ props }) => ({
        userInterview: [
            userInterviewsLogic.findMounted()?.values.userInterviews.find((interview) => interview.id === props.id) ||
                null,
            {
                loadUserInterview: async (id: string): Promise<UserInterviewType | null> => {
                    try {
                        return await api.userInterviews.get(id)
                    } catch {
                        return null
                    }
                },
                updateUserInterview: async (data: { summary: string }): Promise<UserInterviewType> => {
                    return await api.userInterviews.update(props.id, data)
                },
            },
        ],
    })),
    selectors(({ props }) => ({
        breadcrumbs: [
            (s) => [s.userInterview],
            (userInterview): Breadcrumb[] => [
                {
                    key: 'UserInterviews',
                    name: 'User interviews',
                    path: urls.userInterviews(),
                    iconType: 'user_interview',
                },
                {
                    key: props.id,
                    name: userInterview?.interviewee_emails?.join(', '),
                    path: urls.userInterview(props.id),
                    iconType: 'user_interview',
                },
            ],
        ],
    })),
    afterMount(({ actions, props }) => {
        if (props.id) {
            actions.loadUserInterview(props.id)
        }
    }),
])
