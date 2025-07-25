import { kea, path, actions, props, afterMount, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { optOutListLogicType } from './optOutListLogicType'
import { lemonToast } from '@posthog/lemon-ui'
import { MessageCategory } from './optOutCategoriesLogic'

export type OptOutEntry = {
    identifier: string
    source: string
    updatedAt: string
}

export type OptOutListLogicProps = {
    category?: MessageCategory
}

export const optOutListLogic = kea<optOutListLogicType>([
    path(['products', 'messaging', 'frontend', 'OptOuts', 'optOutListLogic']),
    props({} as OptOutListLogicProps),
    actions({
        loadUnsubscribeLink: true,
        setSelectedIdentifier: (identifier: string | null) => ({ identifier }),
    }),
    reducers({
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

    afterMount(({ actions }) => {
        actions.loadOptOutPersons()
    }),
])
