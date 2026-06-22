import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { LogSeverityLevel } from '~/queries/schema/schema-general'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import type { facetRailLogicType } from './facetRailLogicType'

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
        toggleSeverityLevel: (level: LogSeverityLevel) => ({ level }),
        toggleServiceName: (name: string) => ({ name }),
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
        toggleSeverityLevel: ({ level }) => {
            const { severityLevels } = logsViewerFiltersLogic({ id: props.id }).values
            actions.setSeverityLevels(toggleMembership(severityLevels, level))
        },
        toggleServiceName: ({ name }) => {
            const { serviceNames } = logsViewerFiltersLogic({ id: props.id }).values
            actions.setServiceNames(toggleMembership(serviceNames, name))
        },
    })),
])
