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

        initializeDefaultData: true,
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
        initializeDefaultData: async () => {
            const categoryDefinitions = [
                { name: 'Feature request', statuses: ['New', 'Great idea', 'Ignore', 'Done'] },
                { name: 'Feedback', statuses: ['New', 'Acknowledged'] },
                { name: 'Bug', statuses: ['New', 'Confirmed bug', 'Not a bug', 'Fixed'] },
            ]

            const topicNames = ['Auth', 'Payments', 'User interface']

            for (const categoryDef of categoryDefinitions) {
                const category = await api.feedback.categories.create({ name: categoryDef.name })
                for (const statusName of categoryDef.statuses) {
                    await api.feedback.statuses.create({ name: statusName, category: category.id })
                }
            }

            for (const topicName of topicNames) {
                await api.feedback.topics.create({ name: topicName })
            }

            actions.loadFeedbackCategories()
            actions.loadFeedbackStatuses()
            actions.loadFeedbackTopics()
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
