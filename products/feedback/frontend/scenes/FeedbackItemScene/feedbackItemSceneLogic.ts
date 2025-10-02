import { actions, afterMount, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FeedbackItem } from '../../models'
import type { feedbackItemSceneLogicType } from './feedbackItemSceneLogicType'

export interface FeedbackItemSceneLogicProps {
    feedbackItemId: string
}

export const feedbackItemSceneLogic = kea<feedbackItemSceneLogicType>([
    path((key) => ['products', 'feedback', 'scenes', 'FeedbackItemScene', 'feedbackItemSceneLogic', key]),
    props({} as FeedbackItemSceneLogicProps),
    key((props) => props.feedbackItemId || ''),

    actions({
        loadFeedbackItem: true,
        updateStatus: (statusId: string) => ({ statusId }),
        updateAssignment: (userId: number | null) => ({ userId }),
        updateCategory: (categoryId: string) => ({ categoryId }),
        updateTopic: (topicId: string) => ({ topicId }),
    }),

    loaders(({ props }) => ({
        feedbackItem: [
            null as FeedbackItem | null,
            {
                loadFeedbackItem: async () => {
                    const response = await api.feedback.items.get(props.feedbackItemId)

                    return response
                },
            },
        ],
    })),

    listeners(({ actions, props }) => ({
        updateStatus: async ({ statusId }) => {
            await api.feedback.items.update(props.feedbackItemId, { status_id: statusId } as any)
            actions.loadFeedbackItem()
        },
        updateAssignment: async ({ userId }) => {
            await api.feedback.items.update(props.feedbackItemId, { assigned_user_id: userId } as any)
            actions.loadFeedbackItem()
        },
        updateCategory: async ({ categoryId }) => {
            await api.feedback.items.update(props.feedbackItemId, { category_id: categoryId, status_id: null } as any)
            actions.loadFeedbackItem()
        },
        updateTopic: async ({ topicId }) => {
            await api.feedback.items.update(props.feedbackItemId, { topic_id: topicId } as any)
            actions.loadFeedbackItem()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadFeedbackItem()
    }),
])
