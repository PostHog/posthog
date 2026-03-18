import { actions, afterMount, connect, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'

import { MessageCategory } from './optOutCategoriesLogic'
import type { optOutListLogicType } from './optOutListLogicType'
import { optOutSceneLogic } from './optOutSceneLogic'

export type OptOutEntry = {
    identifier: string
    source: string
    updated_at: string
}

export type OptOutPersonPreference = {
    identifier: string
    preferences: Record<string, boolean>
}

export type PaginatedOptOuts = CountedPaginatedResponse<OptOutEntry>

export type OptOutListLogicProps = {
    category?: MessageCategory
}

export const optOutListLogic = kea<optOutListLogicType>([
    key((props) => props.category?.id || '$all'),
    path(['products', 'workflows', 'frontend', 'OptOuts', 'optOutListLogic']),
    props({} as OptOutListLogicProps),
    connect(() => ({
        values: [optOutSceneLogic, ['preferencesUrlLoading']],
        actions: [optOutSceneLogic, ['openPreferencesPage']],
    })),
    actions({
        loadUnsubscribeLink: true,
        setPersonsModalOpen: (open: boolean) => ({ open }),
        setManagePreferencesModalOpen: (open: boolean) => ({ open }),
        setSelectedIdentifier: (identifier: string | null) => ({ identifier }),
        setCurrentPage: (page: number) => ({ page }),
        loadNextPage: true,
        loadPreviousPage: true,
    }),
    reducers({
        personsModalOpen: [
            false,
            {
                setPersonsModalOpen: (_, { open }) => open,
                setSelectedIdentifier: (open, { identifier }) => {
                    if (!identifier) {
                        return false
                    }
                    return open
                },
            },
        ],
        managePreferencesModalOpen: [
            false,
            {
                setManagePreferencesModalOpen: (_, { open }) => open,
                setSelectedIdentifier: (open, { identifier }) => {
                    if (!identifier) {
                        return false
                    }
                    return open
                },
            },
        ],
        selectedIdentifier: [
            null as string | null,
            {
                setSelectedIdentifier: (_, { identifier }) => identifier,
            },
        ],
        currentPage: [
            1,
            {
                setCurrentPage: (_, { page }) => page,
                loadOptOutPersonsSuccess: () => 1, // Reset to page 1 on initial load
                loadNextPageSuccess: (state) => state + 1,
                loadPreviousPageSuccess: (state) => Math.max(1, state - 1),
            },
        ],
    }),
    loaders(({ props, values }) => ({
        optOutPersons: {
            __default: { count: 0, next: null, previous: null, results: [] } as PaginatedOptOuts,
            loadOptOutPersons: async (): Promise<PaginatedOptOuts> => {
                try {
                    return await api.messaging.getMessageOptOuts(props.category?.key, 1)
                } catch {
                    lemonToast.error('Failed to load opt-out persons')
                    return { count: 0, next: null, previous: null, results: [] }
                }
            },
            loadNextPage: async (): Promise<PaginatedOptOuts> => {
                const nextPage = values.currentPage + 1
                try {
                    const result = await api.messaging.getMessageOptOuts(props.category?.key, nextPage)
                    return result
                } catch {
                    lemonToast.error('Failed to load next page')
                    return values.optOutPersons
                }
            },
            loadPreviousPage: async (): Promise<PaginatedOptOuts> => {
                const prevPage = Math.max(1, values.currentPage - 1)
                try {
                    const result = await api.messaging.getMessageOptOuts(props.category?.key, prevPage)
                    return result
                } catch {
                    lemonToast.error('Failed to load previous page')
                    return values.optOutPersons
                }
            },
        },
    })),
    afterMount(({ props, actions }) => {
        // If no category is provided or it's a marketing category, load opt-out persons
        if (!props.category?.id || props.category?.category_type === 'marketing') {
            actions.loadOptOutPersons()
        }
    }),
])
