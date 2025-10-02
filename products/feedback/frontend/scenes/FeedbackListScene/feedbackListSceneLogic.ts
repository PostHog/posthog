import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'

import { FeedbackItem } from '../../models'
import type { feedbackListSceneLogicType } from './feedbackListSceneLogicType'

export const feedbackListSceneLogic = kea<feedbackListSceneLogicType>([
    path(['products', 'feedback', 'scenes', 'FeedbackListScene', 'feedbackListSceneLogic']),

    actions({
        setStatusFilter: (status: string | null) => ({ status }),
        setCategoryFilter: (category: string | null) => ({ category }),
        setTopicFilter: (topic: string | null) => ({ topic }),
        loadFeedbackItems: true,
    }),

    reducers({
        statusFilter: [
            null as string | null,
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
                    const response = await api.feedback.items.list({
                        category: values.categoryFilter ? values.categoryFilter : undefined,
                        topic: values.topicFilter ? values.topicFilter : undefined,
                        status: values.statusFilter ? values.statusFilter : undefined,
                    })

                    return response.results
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
])
