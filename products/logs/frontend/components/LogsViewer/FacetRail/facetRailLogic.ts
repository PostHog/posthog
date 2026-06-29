import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { LogSeverityLevel } from '~/queries/schema/schema-general'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import type { facetRailLogicType } from './facetRailLogicType'
import { FacetSource, toggleResourceAttributeFilter } from './facets'

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
        actions: [logsViewerFiltersLogic({ id: props.id }), ['setSeverityLevels', 'setServiceNames', 'setFilterGroup']],
    })),

    actions({
        // Generic toggle: the rail is config-driven, so a single action writes a value into whichever
        // filter field/group the facet's source maps to (see FacetConfig.source).
        toggleFacetValue: (source: FacetSource, value: string) => ({ source, value }),
        toggleFacetCollapsed: (facetKey: string) => ({ facetKey }),
        // Free-text filter over the facet *fields* shown in the rail (not their values). URL-synced by
        // logsSceneLogic on the main scene, so deliberately not persisted here.
        setFacetNameSearch: (search: string) => ({ search }),
    }),

    reducers({
        facetNameSearch: [
            '',
            {
                setFacetNameSearch: (_, { search }) => search,
            },
        ],
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
        toggleFacetValue: ({ source, value }) => {
            const { severityLevels, serviceNames, filterGroup } = logsViewerFiltersLogic({ id: props.id }).values
            if (source.type === 'resourceAttribute') {
                // Selection lives as a log_resource_attribute filter inside the group.
                actions.setFilterGroup(toggleResourceAttributeFilter(filterGroup, source.key, value), false)
            } else if (source.filterKey === 'severityLevels') {
                actions.setSeverityLevels(toggleMembership(severityLevels, value as LogSeverityLevel))
            } else if (source.filterKey === 'serviceNames') {
                actions.setServiceNames(toggleMembership(serviceNames, value))
            } else {
                // Adding a new column filterKey without wiring its setter here is a compile error.
                source.filterKey satisfies never
            }
        },
    })),
])
