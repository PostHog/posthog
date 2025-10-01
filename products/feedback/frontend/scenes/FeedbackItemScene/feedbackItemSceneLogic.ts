import { kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { MOCK_FEEDBACK_ITEMS } from '../../mocks'
import { FeedbackItem } from '../../types'
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
                    return MOCK_FEEDBACK_ITEMS.find((item) => item.id === props.feedbackItemId)
                },
            },
        ],
    })),
])
