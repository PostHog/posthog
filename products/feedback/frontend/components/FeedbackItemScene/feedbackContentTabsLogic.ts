import { actions, kea, path, reducers } from 'kea'

import type { feedbackContentTabsLogicType } from './feedbackContentTabsLogicType'

export const feedbackContentTabsLogic = kea<feedbackContentTabsLogicType>([
    path(['products', 'feedback', 'components', 'FeedbackItemScene', 'feedbackContentTabsLogic']),

    actions({
        setCurrentTab: (tab: 'attachments' | 'recording') => ({ tab }),
        setSelectedAttachmentIndex: (index: number) => ({ index }),
    }),

    reducers({
        currentTab: [
            'attachments' as 'attachments' | 'recording',
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
        selectedAttachmentIndex: [
            0,
            {
                setSelectedAttachmentIndex: (_, { index }) => index,
            },
        ],
    }),
])
