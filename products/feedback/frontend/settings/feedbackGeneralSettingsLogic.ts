import { actions, kea, path, reducers } from 'kea'

import type { feedbackGeneralSettingsLogicType } from './feedbackGeneralSettingsLogicType'

export const DEFAULT_FEEDBACK_TYPES: string[] = ['bug', 'feature', 'improvement']

export const feedbackGeneralSettingsLogic = kea<feedbackGeneralSettingsLogicType>([
    path(['products', 'feedback', 'settings', 'feedbackGeneralSettingsLogic']),

    actions({
        addFeedbackType: (key: string) => ({ key }),
        removeFeedbackType: (index: number) => ({ index }),
    }),

    reducers({
        feedbackTypes: [
            DEFAULT_FEEDBACK_TYPES as string[],
            { persist: true, storageKey: 'feedback-types-v2' },
            {
                addFeedbackType: (state, { key }) => [...state, key],
                removeFeedbackType: (state, { index }) => state.filter((_, i) => i !== index),
            },
        ],
    }),
])
