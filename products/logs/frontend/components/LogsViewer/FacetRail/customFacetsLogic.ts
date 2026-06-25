import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { logsCustomFacetsCreate, logsCustomFacetsList } from '../../../generated/api'
import { CustomFacetApi } from '../../../generated/api.schemas'
import type { customFacetsLogicType } from './customFacetsLogicType'
import { FacetConfig, entryToFacetConfig } from './facets'

// Per-user, per-project custom facets — the rail's "Custom" group. A singleton: the set is the same
// across every LogsViewer instance, persisted server-side via the logs/custom_facets endpoint.
export const customFacetsLogic = kea<customFacetsLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'FacetRail', 'customFacetsLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadCustomFacets: true,
        setCustomFacets: (entries: CustomFacetApi[]) => ({ entries }),
        addCustomFacet: (key: string, attributeType: CustomFacetApi['attribute_type']) => ({ key, attributeType }),
        removeCustomFacet: (key: string) => ({ key }),
    }),

    reducers({
        customFacetEntries: [
            [] as CustomFacetApi[],
            {
                setCustomFacets: (_, { entries }) => entries,
                // Optimistic: reflect the change in the rail immediately, then persist (listener below).
                addCustomFacet: (state, { key, attributeType }) =>
                    state.some((f) => f.key === key) ? state : [...state, { key, attribute_type: attributeType }],
                removeCustomFacet: (state, { key }) => state.filter((f) => f.key !== key),
            },
        ],
    }),

    selectors({
        customFacets: [
            (s) => [s.customFacetEntries],
            (entries: CustomFacetApi[]): FacetConfig[] =>
                entries.map(entryToFacetConfig).filter((f): f is FacetConfig => f !== null),
        ],
    }),

    listeners(({ values, actions }) => {
        // Reducers run before listeners, so `customFacetEntries` already reflects the add/remove here —
        // we just persist the new full set (the endpoint replaces it wholesale).
        const persist = async (): Promise<void> => {
            if (!values.currentTeamId) {
                return
            }
            try {
                await logsCustomFacetsCreate(String(values.currentTeamId), values.customFacetEntries)
            } catch {
                // The optimistic reducer update already landed; reload to fall back to the server's truth
                // so the rail never keeps showing a facet that wasn't actually saved.
                lemonToast.error('Failed to save custom facets')
                actions.loadCustomFacets()
            }
        }
        return {
            loadCustomFacets: async (_, breakpoint) => {
                if (!values.currentTeamId) {
                    return
                }
                // Only the request is in the try — breakpoint() throws to cancel a superseded run and
                // must propagate to kea, not be caught here as a load failure.
                let entries: CustomFacetApi[]
                try {
                    entries = await logsCustomFacetsList(String(values.currentTeamId))
                } catch {
                    lemonToast.error('Failed to load custom facets')
                    return
                }
                breakpoint()
                actions.setCustomFacets(entries)
            },
            addCustomFacet: () => persist(),
            removeCustomFacet: () => persist(),
        }
    }),

    afterMount(({ actions }) => actions.loadCustomFacets()),
])
