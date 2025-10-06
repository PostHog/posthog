import { actions, afterMount, connect, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

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

export type OptOutListLogicProps = {
    category?: MessageCategory
}

export const optOutListLogic = kea<optOutListLogicType>([
    key((props) => props.category?.id || '$all'),
    path(['products', 'messaging', 'frontend', 'OptOuts', 'optOutListLogic']),
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
    }),
    loaders(({ props }) => ({
        optOutPersons: {
            __default: [] as OptOutEntry[],
            loadOptOutPersons: async (): Promise<OptOutEntry[]> => {
                try {
                    return await api.messaging.getMessageOptOuts(props.category?.key)
                } catch {
                    lemonToast.error('Failed to load opt-out persons')
                    return []
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
