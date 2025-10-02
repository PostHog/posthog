import { actions, events, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FeedbackItemCategory, FeedbackItemStatus, FeedbackItemTopic } from '../models'
import type { feedbackGeneralSettingsLogicType } from './feedbackGeneralSettingsLogicType'

export const feedbackGeneralSettingsLogic = kea<feedbackGeneralSettingsLogicType>([
    path(['products', 'feedback', 'settings', 'feedbackGeneralSettingsLogic']),

    actions({
        loadFeedbackTopics: true,
        loadFeedbackCategories: true,
        loadFeedbackStatuses: true,

        createFeedbackTopic: (name: string) => ({ name }),
        deleteFeedbackTopic: (id: string) => ({ id }),

        createFeedbackCategory: (name: string) => ({ name }),
        deleteFeedbackCategory: (id: string) => ({ id }),

        createFeedbackStatus: (name: string, categoryId: string) => ({ name, categoryId }),
        deleteFeedbackStatus: (id: string) => ({ id }),
    }),

    loaders(() => ({
        feedbackTopics: [
            [] as FeedbackItemTopic[],
            {
                loadFeedbackTopics: async () => {
                    const response = await api.feedback.topics.list()
                    return response.results
                },
            },
        ],
        feedbackCategories: [
            [] as FeedbackItemCategory[],
            {
                loadFeedbackCategories: async () => {
                    const response = await api.feedback.categories.list()
                    return response.results
                },
            },
        ],
        feedbackStatuses: [
            [] as FeedbackItemStatus[],
            {
                loadFeedbackStatuses: async () => {
                    const response = await api.feedback.statuses.list()
                    return response.results
                },
            },
        ],
    })),

    selectors({
        getStatusesForCategory: [
            (s) => [s.feedbackStatuses],
            (statuses) => (categoryId: string) => statuses.filter((status) => status.category === categoryId),
        ],
    }),

    listeners(({ actions }) => ({
        createFeedbackTopic: async ({ name }) => {
            await api.feedback.topics.create({ name })
            actions.loadFeedbackTopics()
        },
        deleteFeedbackTopic: async ({ id }) => {
            await api.feedback.topics.delete(id)
            actions.loadFeedbackTopics()
        },
        createFeedbackCategory: async ({ name }) => {
            await api.feedback.categories.create({ name })
            actions.loadFeedbackCategories()
        },
        deleteFeedbackCategory: async ({ id }) => {
            await api.feedback.categories.delete(id)
            actions.loadFeedbackCategories()
        },
        createFeedbackStatus: async ({ name, categoryId }) => {
            await api.feedback.statuses.create({ name, category: categoryId })
            actions.loadFeedbackCategories()
        },
        deleteFeedbackStatus: async ({ id }) => {
            await api.feedback.statuses.delete(id)
            actions.loadFeedbackCategories()
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadFeedbackTopics()
            actions.loadFeedbackCategories()
            actions.loadFeedbackStatuses()
        },
    })),
])
