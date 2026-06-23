import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { LogSeverityLevel } from '~/queries/schema/schema-general'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import type { facetRailLogicType } from './facetRailLogicType'
import { FacetFilterKey } from './facets'

export interface FacetRailLogicProps {
    id: string
}

function toggleMembership<T>(values: readonly T[] | undefined | null, value: T): T[] {
    const current = values ?? []
    return current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
}

// The rail is a lens over the existing filter model — facet toggles write straight back to
// logsViewerFiltersLogic's reducers, so URL sync, saved views, and the chips bar stay in step.
export const facetRailLogic = kea<facetRailLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'FacetRail', 'facetRailLogic']),
    props({ id: 'default' } as FacetRailLogicProps),
    key((props) => props.id),

    connect((props: FacetRailLogicProps) => ({
        actions: [logsViewerFiltersLogic({ id: props.id }), ['setSeverityLevels', 'setServiceNames']],
    })),

    actions({
        // Generic toggle: the rail is config-driven, so a single action writes a value into whichever
        // filter field the facet maps to (see FacetConfig.filterKey).
        toggleFacetValue: (filterKey: FacetFilterKey, value: string) => ({ filterKey, value }),
        toggleFacetCollapsed: (facetKey: string) => ({ facetKey }),
    }),

    reducers({
        collapsedFacets: [
            [] as string[],
            { persist: true },
            {
                toggleFacetCollapsed: (state, { facetKey }) =>
                    state.includes(facetKey) ? state.filter((k) => k !== facetKey) : [...state, facetKey],
            },
        ],
    }),

    listeners(({ props, actions }) => ({
        toggleFacetValue: ({ filterKey, value }) => {
            const { severityLevels, serviceNames } = logsViewerFiltersLogic({ id: props.id }).values
            if (filterKey === 'severityLevels') {
                actions.setSeverityLevels(toggleMembership(severityLevels, value as LogSeverityLevel))
            } else if (filterKey === 'serviceNames') {
                actions.setServiceNames(toggleMembership(serviceNames, value))
            } else {
                // Adding a new FacetFilterKey without wiring its setter here is a compile error.
                filterKey satisfies never
            }
        },
    })),
])
