import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
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
        openFeedbackItem: (id: string) => ({ id }),
        updateStatus: (feedbackItemId: string, statusId: string) => ({ feedbackItemId, statusId }),
        updateAssignment: (feedbackItemId: string, userId: number | null) => ({ feedbackItemId, userId }),
        updateCategory: (feedbackItemId: string, categoryId: string) => ({ feedbackItemId, categoryId }),
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

    listeners(({ actions }) => ({
        openFeedbackItem: ({ id }) => {
            router.actions.push(`/feedback/${id}`)
        },
        updateStatus: async ({ feedbackItemId, statusId }) => {
            await api.feedback.items.update(feedbackItemId, { status_id: statusId } as any)
            actions.loadFeedbackItems()
        },
        updateAssignment: async ({ feedbackItemId, userId }) => {
            await api.feedback.items.update(feedbackItemId, { assigned_user_id: userId } as any)
            actions.loadFeedbackItems()
        },
        updateCategory: async ({ feedbackItemId, categoryId }) => {
            await api.feedback.items.update(feedbackItemId, { category_id: categoryId, status_id: null } as any)
            actions.loadFeedbackItems()
        },
    })),
])
