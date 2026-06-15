import { actions, afterMount, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { objectsEqual } from 'lib/utils'

import { BlastRadiusApi } from 'products/workflows/frontend/generated/api.schemas'

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
        setBlastRadiusError: (error: string | null) => ({ error }),
    }),
    reducers(() => ({
        filters: {
            setFilters: (_, { filters }) => filters,
        },
        blastRadiusError: [
            null as string | null,
            {
                loadBlastRadius: () => null,
                setBlastRadiusError: (_, { error }) => error,
            },
        ],
    })),
    loaders(({ props }) => ({
        blastRadius: [
            null as BlastRadiusApi | null,
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
    listeners(({ actions }) => ({
        loadBlastRadiusFailure: ({ errorObject }) => {
            const apiError = errorObject as ApiError | undefined
            const message =
                apiError?.detail ||
                (errorObject as Error | undefined)?.message ||
                "Couldn't validate audience size. Your filters may not be supported."
            actions.setBlastRadiusError(message)
        },
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
