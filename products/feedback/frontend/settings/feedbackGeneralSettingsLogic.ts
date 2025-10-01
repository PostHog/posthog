import { actions, kea, path, reducers } from 'kea'

import type { feedbackGeneralSettingsLogicType } from './feedbackGeneralSettingsLogicType'

export const DEFAULT_FEEDBACK_CATEGORIES: string[] = ['bug', 'feature', 'improvement']
export const DEFAULT_FEEDBACK_TOPICS: string[] = ['Dashboard', 'Search', 'Export', 'Onboarding']

export const feedbackGeneralSettingsLogic = kea<feedbackGeneralSettingsLogicType>([
    path(['products', 'feedback', 'settings', 'feedbackGeneralSettingsLogic']),

    actions({
        addFeedbackCategory: (key: string) => ({ key }),
        removeFeedbackCategory: (index: number) => ({ index }),
        addFeedbackTopic: (key: string) => ({ key }),
        removeFeedbackTopic: (index: number) => ({ index }),
    }),

    reducers({
        feedbackCategories: [
            DEFAULT_FEEDBACK_CATEGORIES as string[],
            { persist: true },
            {
                addFeedbackCategory: (state, { key }) => [...state, key],
                removeFeedbackCategory: (state, { index }) => state.filter((_, i) => i !== index),
            },
        ],
        feedbackTopics: [
            DEFAULT_FEEDBACK_TOPICS as string[],
            { persist: true },
            {
                addFeedbackTopic: (state, { key }) => [...state, key],
                removeFeedbackTopic: (state, { index }) => state.filter((_, i) => i !== index),
            },
        ],
    }),
])
