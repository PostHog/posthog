import { actions, kea, path, reducers } from 'kea'

import type { tracingConfigLogicType } from './tracingConfigLogicType'

/** Display-only preferences for the tracing scene — never affects the query. */
export const tracingConfigLogic = kea<tracingConfigLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingConfigLogic']),

    actions({
        setFacetRailCollapsed: (facetRailCollapsed: boolean) => ({ facetRailCollapsed }),
    }),

    reducers({
        facetRailCollapsed: [
            false,
            { persist: true },
            {
                setFacetRailCollapsed: (_, { facetRailCollapsed }) => facetRailCollapsed,
            },
        ],
    }),
])
