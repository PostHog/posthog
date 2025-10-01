import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { MOCK_FEEDBACK_ITEMS } from '../../mocks'
import { FeedbackItem } from '../../models'
import { FeedbackStatus } from '../../types'
import type { feedbackListSceneLogicType } from './feedbackListSceneLogicType'

export const feedbackListSceneLogic = kea<feedbackListSceneLogicType>([
    path(['products', 'feedback', 'scenes', 'FeedbackListScene', 'feedbackListSceneLogic']),

    actions({
        setStatusFilter: (status: FeedbackStatus | null) => ({ status }),
        setCategoryFilter: (category: string | null) => ({ category }),
        setTopicFilter: (topic: string | null) => ({ topic }),

        loadFeedbackItems: true,
        openFeedbackItem: (id: string) => ({ id }),
    }),

    reducers({
        statusFilter: [
            null as FeedbackStatus | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        categoryFilter: [
            null as string | null,
            {
                setCategoryFilter: (_, { category }) => category,
            },
        ],
        topicFilter: [
            null as string | null,
            {
                setTopicFilter: (_, { topic }) => topic,
            },
        ],
    }),

    loaders(({ values }) => ({
        feedbackItems: [
            [] as FeedbackItem[],
            {
                loadFeedbackItems: async () => {
                    await new Promise((resolve) => setTimeout(resolve, 1000))

                    let filtered = MOCK_FEEDBACK_ITEMS

                    if (values.statusFilter) {
                        filtered = filtered.filter((item) => item.status === values.statusFilter)
                    }

                    if (values.categoryFilter) {
                        filtered = filtered.filter((item) => item.category === values.categoryFilter)
                    }

                    if (values.topicFilter) {
                        filtered = filtered.filter((item) => item.topic === values.topicFilter)
                    }

                    return filtered
                },
            },
        ],
    })),

    subscriptions(({ actions }) => ({
        categoryFilter: () => {
            return actions.loadFeedbackItems()
        },
        statusFilter: () => {
            return actions.loadFeedbackItems()
        },
        topicFilter: () => {
            return actions.loadFeedbackItems()
        },
    })),

    listeners(() => ({
        openFeedbackItem: ({ id }) => {
            router.actions.push(`/feedback/${id}`)
        },
    })),
])
