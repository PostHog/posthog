import { afterMount, kea, key, path, props } from 'kea'
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
    key((props) => props.feedbackItemId),

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

    afterMount(({ actions }) => {
        actions.loadFeedbackItem()
    }),
])
