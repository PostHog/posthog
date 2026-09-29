import { MakeLogicType, actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import {
    HogQLFilters,
    MCPModelBreakdownItem,
    MCPModelBreakdownQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'

import { freezeModelDateRange } from './modelBreakdown'

export const MODEL_PAGE_SIZE = 50

interface ModelBreakdownLogicProps {
    filters: HogQLFilters
}

interface ModelPage {
    results: MCPModelBreakdownItem[]
    hasMore: boolean
    offset: number
}

export interface modelBreakdownLogicValues {
    expanded: boolean
    modelPage: ModelPage | null
    modelPageLoading: boolean
    loadFailed: boolean
    requestedOffset: number
}

export interface modelBreakdownLogicActions {
    setExpanded: (expanded: boolean) => { expanded: boolean }
    loadModels: (offset: number) => { offset: number }
    loadModelsSuccess: (
        modelPage: ModelPage | null,
        payload?: { offset: number }
    ) => { modelPage: ModelPage | null; payload?: { offset: number } }
    loadModelsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
}

export type modelBreakdownLogicType = MakeLogicType<
    modelBreakdownLogicValues,
    modelBreakdownLogicActions,
    ModelBreakdownLogicProps
>

export const modelBreakdownLogic = kea<modelBreakdownLogicType>([
    props({} as ModelBreakdownLogicProps),
    key(({ filters }) => JSON.stringify(filters)),
    path((key) => ['products', 'mcp_analytics', 'frontend', 'dashboard', 'modelBreakdownLogic', key]),
    actions({
        setExpanded: (expanded: boolean) => ({ expanded }),
        loadModels: (offset: number) => ({ offset }),
    }),
    loaders(({ props, cache }) => ({
        modelPage: [
            null as ModelPage | null,
            {
                loadModels: async ({ offset }: { offset: number }, breakpoint): Promise<ModelPage> => {
                    const { dateRange, properties, filterTestAccounts } = props.filters
                    cache.dateRange ??= freezeModelDateRange(dateRange, teamLogic.values.timezone)
                    const response = (await api.query({
                        kind: NodeKind.MCPModelBreakdownQuery,
                        dateRange: cache.dateRange,
                        properties,
                        filterTestAccounts,
                        includeAllModels: true,
                        limit: MODEL_PAGE_SIZE,
                        offset,
                    })) as MCPModelBreakdownQueryResponse
                    breakpoint()
                    return { results: response.results, hasMore: response.hasMore ?? false, offset }
                },
            },
        ],
    })),
    reducers({
        expanded: [false, { setExpanded: (_, { expanded }) => expanded }],
        requestedOffset: [0, { loadModels: (_, { offset }) => offset }],
        loadFailed: [false, { loadModels: () => false, loadModelsFailure: () => true }],
    }),
    listeners(({ actions, values }) => ({
        setExpanded: ({ expanded }) => {
            if (expanded && !values.modelPage && !values.modelPageLoading) {
                actions.loadModels(0)
            }
        },
    })),
])
