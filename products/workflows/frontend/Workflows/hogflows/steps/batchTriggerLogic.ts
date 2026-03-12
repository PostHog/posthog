import { actions, afterMount, kea, key, path, props, propsChanged, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { objectsEqual } from 'lib/utils'

import { HogFlowAction } from '../types'
import type { batchTriggerLogicType } from './batchTriggerLogicType'

export const BLAST_RADIUS_LIMIT = 5000

export interface BatchTriggerLogicProps {
    id?: string | 'new'
    filters?: Extract<HogFlowAction['config'], { type: 'batch' }>['filters']
}

export const batchTriggerLogic = kea<batchTriggerLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'batchTriggerLogic']),
    props({} as BatchTriggerLogicProps),
    key(({ id }) => `batch-trigger-logic-${id || 'new'}`),
    actions({
        loadBlastRadius: true,
    }),
    reducers(() => ({
        filters: {
            setFilters: (_, { filters }) => filters,
        },
    })),
    loaders(({ props }) => ({
        blastRadius: [
            null as { users_affected: number; total_users: number } | null,
            {
                loadBlastRadius: async () => {
                    if (!props.filters) {
                        return null
                    }
                    return await api.hogFlows.getBatchTriggerBlastRadius(props.filters)
                },
            },
        ],
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!oldProps || !objectsEqual(props.filters, oldProps.filters)) {
            actions.loadBlastRadius()
        }
    }),
    afterMount(({ actions }) => {
        actions.loadBlastRadius()
    }),
])
