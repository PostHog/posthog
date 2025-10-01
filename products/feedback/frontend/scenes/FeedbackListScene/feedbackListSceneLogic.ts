import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { FeedbackItem, FeedbackStatus, FeedbackType } from '../../types'
import type { feedbackListSceneLogicType } from './feedbackListSceneLogicType'

const MOCK_FEEDBACK_ITEMS: FeedbackItem[] = [
    {
        id: '1',
        user: 'user@example.com',
        message: 'Love the new dashboard! The insights are really helpful and the UI is much cleaner.',
        type: FeedbackType.Feedback,
        timestamp: '2 hours ago',
        status: FeedbackStatus.Visible,
    },
    {
        id: '2',
        user: 'john@company.com',
        message: 'The search feature is a bit slow and sometimes returns irrelevant results.',
        type: FeedbackType.Bug,
        timestamp: '5 hours ago',
        status: FeedbackStatus.Visible,
    },
    {
        id: '3',
        user: 'sarah@startup.io',
        message: 'Great product overall. Would be nice to have dark mode though.',
        type: FeedbackType.Feedback,
        timestamp: '1 day ago',
        status: FeedbackStatus.Hidden,
    },
    {
        id: '4',
        user: 'mike@tech.com',
        message: 'The onboarding process was smooth and easy to follow. Impressed!',
        type: FeedbackType.Question,
        timestamp: '1 day ago',
        status: FeedbackStatus.Visible,
    },
    {
        id: '5',
        user: 'anna@design.co',
        message: 'Having issues with the export feature. It keeps timing out on large datasets.',
        type: FeedbackType.Bug,
        timestamp: '2 days ago',
        status: FeedbackStatus.Hidden,
    },
]

export const feedbackListSceneLogic = kea<feedbackListSceneLogicType>([
    path(['products', 'feedback', 'scenes', 'FeedbackListScene', 'feedbackListSceneLogic']),

    actions({
        setStatusFilter: (status: FeedbackStatus | null) => ({ status }),
        setTypeFilter: (type: FeedbackType | null) => ({ type }),

        loadFeedbackItems: true,
    }),

    reducers({
        statusFilter: [
            null as FeedbackStatus | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        typeFilter: [
            null as FeedbackType | null,
            {
                setTypeFilter: (_, { type }) => type,
            },
        ],
    }),

    loaders(({ values }) => ({
        feedbackItems: [
            [] as FeedbackItem[],
            {
                loadFeedbackItems: async () => {
                    await new Promise((resolve) => setTimeout(resolve, 1000))

                    if (!values.statusFilter && !values.typeFilter) {
                        return MOCK_FEEDBACK_ITEMS
                    }

                    if (values.statusFilter && values.typeFilter) {
                        return MOCK_FEEDBACK_ITEMS.filter(
                            (item) => item.status === values.statusFilter && item.type === values.typeFilter
                        )
                    }

                    if (values.statusFilter) {
                        return MOCK_FEEDBACK_ITEMS.filter((item) => item.status === values.statusFilter)
                    }

                    if (values.typeFilter) {
                        return MOCK_FEEDBACK_ITEMS.filter((item) => item.type === values.typeFilter)
                    }

                    return MOCK_FEEDBACK_ITEMS
                },
            },
        ],
    })),

    subscriptions(({ actions }) => ({
        typeFilter: () => {
            return actions.loadFeedbackItems()
        },
        statusFilter: () => {
            return actions.loadFeedbackItems()
        },
    })),
])
