import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { MessageAsset } from './hogflows/types'
import type { workflowAssetsLogicType } from './workflowAssetsLogicType'

export interface WorkflowAssetsLogicProps {
    id: string
    /** Scope the list to a single batch run (HogFlowBatchJob id). Omit for the event-triggered/all view. */
    parentRunId?: string
    /** Pre-filter to a single email step, e.g. when arriving from a step's metric. */
    actionId?: string
}

export const workflowAssetsLogic = kea<workflowAssetsLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowAssetsLogic']),
    props({ id: 'new' } as WorkflowAssetsLogicProps),
    key((props) => `${props.id || 'new'}-${props.parentRunId ?? 'all'}-${props.actionId ?? 'all'}`),
    // `downloadPdf` and `loadAssets` are created by the loaders below.
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
                    return await api.hogFlows.getMessageAssets(props.id, {
                        parent_run_id: props.parentRunId,
                        action_id: props.actionId,
                        search: values.search || undefined,
                    })
                },
            },
        ],
        pdf: [
            null as null,
            {
                // Fetch the on-demand PDF as a blob and hand it to the browser as a download.
                downloadPdf: async (asset: MessageAsset) => {
                    try {
                        const blob = await api.hogFlows.getMessageAssetPdf(
                            props.id,
                            asset.invocation_id,
                            asset.action_id
                        )
                        const url = URL.createObjectURL(blob)
                        const link = document.createElement('a')
                        link.href = url
                        link.download = `email-${asset.recipient || asset.invocation_id}.pdf`
                        link.click()
                        // Defer revoke so the click-initiated download can read the blob first.
                        setTimeout(() => URL.revokeObjectURL(url), 1000)
                    } catch {
                        lemonToast.error('Could not generate a PDF for this email. Please try again.')
                    }
                    return null
                },
            },
        ],
    })),
    selectors({
        contentUrl: [
            () => [(_, props) => props.id as string],
            (id): ((asset: MessageAsset) => string) => {
                return (asset: MessageAsset) =>
                    api.hogFlows.getMessageAssetContentUrl(id, asset.invocation_id, asset.action_id)
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
