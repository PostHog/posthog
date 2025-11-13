import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { optOutCategoriesLogicType } from './optOutCategoriesLogicType'

export type MessageCategory = {
    id: string
    key: string
    name: string
    description: string
    public_description: string
    category_type: string
}

export const optOutCategoriesLogic = kea<optOutCategoriesLogicType>([
    path(['products', 'workflows', 'frontend', 'OptOuts', 'optOutCategoriesLogic']),

    actions({
        loadCategories: true,
        deleteCategory: (id: string) => ({ id }),
        openNewCategoryModal: true,
        closeNewCategoryModal: true,
    }),

    loaders({
        categories: {
            __default: [] as MessageCategory[],
            loadCategories: async (): Promise<MessageCategory[]> => {
                const response = await api.messaging.getCategories({ category_type: 'marketing' })
                return response.results || []
            },
        },
    }),

    reducers({
        categories: [
            [] as MessageCategory[],
            {
                loadCategoriesSuccess: (_, { categories }) => categories,
            },
        ],
        isNewCategoryModalOpen: [
            false,
            {
                openNewCategoryModal: () => true,
                closeNewCategoryModal: () => false,
            },
        ],
    }),

    listeners(({ actions }) => ({
        deleteCategory: async ({ id }: { id: string }) => {
            try {
                await api.messaging.updateCategory(id, { deleted: true })
                actions.loadCategories()
            } catch (error) {
                console.error('Failed to delete category:', error)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadCategories()
    }),
])
