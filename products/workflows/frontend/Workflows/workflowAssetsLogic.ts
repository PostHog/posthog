import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import { getMessageAssetContentUrl, getMessageAssets, MessageAsset } from './messageAssetsApi'
import type { workflowAssetsLogicType } from './workflowAssetsLogicType'

export interface WorkflowAssetsLogicProps {
    id: string
    /** Scope the list to a single batch run (HogFlowBatchJob id). Omit for the event-triggered/all view. */
    parentRunId?: string
    /** Pre-filter to a single email step, e.g. when arriving from a step's metric. */
    actionId?: string
    /** Pre-filter to a single invocation — used to deep-link from a log entry to its email. */
    invocationId?: string
}

export const workflowAssetsLogic = kea<workflowAssetsLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowAssetsLogic']),
    props({ id: 'new' } as WorkflowAssetsLogicProps),
    key(
        (props) =>
            `${props.id || 'new'}-${props.parentRunId ?? 'all'}-${props.actionId ?? 'all'}-${props.invocationId ?? 'all'}`
    ),
    actions({
        setSearch: (search: string) => ({ search }),
        openAsset: (asset: MessageAsset) => ({ asset }),
        closeAsset: true,
    }),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        selectedAsset: [
            null as MessageAsset | null,
            {
                openAsset: (_, { asset }) => asset,
                closeAsset: () => null,
            },
        ],
    }),
    lazyLoaders(({ props, values }) => ({
        assets: [
            [] as MessageAsset[],
            {
                loadAssets: async () => {
                    if (!props.id || props.id === 'new') {
                        return []
                    }
                    return await getMessageAssets(props.id, {
                        parent_run_id: props.parentRunId,
                        action_id: props.actionId,
                        invocation_id: props.invocationId,
                        search: values.search || undefined,
                    })
                },
            },
        ],
    })),
    selectors({
        contentUrl: [
            () => [(_, props) => props.id as string],
            (id): ((asset: MessageAsset) => string) => {
                return (asset: MessageAsset) => getMessageAssetContentUrl(id, asset.invocation_id, asset.action_id)
            },
        ],
    }),
    listeners(({ actions }) => ({
        // Debounce so typing in the search box doesn't fire a request per keystroke.
        setSearch: async (_, breakpoint) => {
            await breakpoint(250)
            actions.loadAssets()
        },
    })),
])
