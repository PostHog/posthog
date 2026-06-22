import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { LogSeverityLevel } from '~/queries/schema/schema-general'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import type { fieldRailLogicType } from './fieldRailLogicType'
import { FieldSource, toggleResourceAttributeFilter } from './fields'

export interface FieldRailLogicProps {
    id: string
}

function toggleMembership<T>(values: readonly T[] | undefined | null, value: T): T[] {
    const current = values ?? []
    return current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
}

// The rail is a lens over the existing filter model — field toggles write straight back to
// logsViewerFiltersLogic's reducers, so URL sync, saved views, and the chips bar stay in step.
export const fieldRailLogic = kea<fieldRailLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'FieldRail', 'fieldRailLogic']),
    props({ id: 'default' } as FieldRailLogicProps),
    key((props) => props.id),

    connect((props: FieldRailLogicProps) => ({
        actions: [logsViewerFiltersLogic({ id: props.id }), ['setSeverityLevels', 'setServiceNames', 'setFilterGroup']],
    })),

    actions({
        // Generic toggle: the rail is config-driven, so a single action writes a value into whichever
        // filter field/group the field's source maps to (see FieldConfig.source).
        toggleFieldValue: (source: FieldSource, value: string) => ({ source, value }),
        toggleFieldCollapsed: (fieldKey: string) => ({ fieldKey }),
    }),

    reducers({
        collapsedFields: [
            [] as string[],
            { persist: true },
            {
                toggleFieldCollapsed: (state, { fieldKey }) =>
                    state.includes(fieldKey) ? state.filter((k) => k !== fieldKey) : [...state, fieldKey],
            },
        ],
    }),

    listeners(({ props, actions }) => ({
        toggleFieldValue: ({ source, value }) => {
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
