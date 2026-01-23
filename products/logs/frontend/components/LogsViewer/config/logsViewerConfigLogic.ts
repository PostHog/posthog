import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { LogsViewerConfig, LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

import type { logsViewerConfigLogicType } from './logsViewerConfigLogicType'

export const DEFAULT_LOGS_VIEWER_CONFIG: LogsViewerConfig = {
    filters: {
        dateRange: { date_from: '-1h', date_to: null },
        searchTerm: '',
        severityLevels: [],
        serviceNames: [],
        filterGroup: { type: FilterLogicalOperator.And, values: [] },
    },
}

export interface LogsViewerConfigProps {
    id: string
    config: LogsViewerConfig
    onFiltersChanged?: (filters: LogsViewerFilters) => void
    onConfigChanged?: (config: LogsViewerConfig) => void
}

export const logsViewerConfigLogic = kea<logsViewerConfigLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'config', 'logsViewerConfigLogic']),
    props({ id: 'default', config: DEFAULT_LOGS_VIEWER_CONFIG } as LogsViewerConfigProps),
    key((props) => props.id),

    connect(() => ({
        actions: [teamLogic, ['addProductIntent']],
    })),

    actions({
        setFilters: (filters: LogsViewerFilters) => ({ filters }), // Does not trigger analytics
        setFilter: (filter: keyof LogsViewerFilters, value: LogsViewerFilters[keyof LogsViewerFilters]) => ({
            filter,
            value,
        }),
    }),

    reducers(({ props }) => ({
        filters: [
            props.config.filters,
            {
                setFilters: (_, { filters }) => filters,
                setFilter: (state, { filter, value }) => ({
                    ...state,
                    [filter]: value,
                }),
            },
        ],
    })),

    selectors({
        config: [(s) => [s.filters], (filters: LogsViewerFilters): LogsViewerConfig => ({ filters })],
    }),

    listeners(({ actions }) => ({
        setFilter: ({ filter, value }) => {
            if (!value) {
                return
            }
            const event = 'logs filter changed'
            let attributes: Record<string, any> = {}

            switch (filter) {
                case 'dateRange':
                    attributes.filter_type = 'date_range'
                    attributes.date_from = (value as LogsViewerFilters['dateRange']).date_from
                    attributes.date_to = (value as LogsViewerFilters['dateRange']).date_to
                    break
                case 'searchTerm':
                    attributes.filter_type = 'search'
                    attributes.search_term_length = (value as LogsViewerFilters['searchTerm'])?.length ?? 0
                    break
                case 'severityLevels':
                    attributes.filter_type = 'severity'
                    attributes.severity_levels = value ?? []
                    break
                case 'serviceNames':
                    attributes.filter_type = 'service'
                    attributes.service_count = (value as LogsViewerFilters['serviceNames'])?.length ?? 0
                    break
                case 'filterGroup':
                    attributes.filter_type = 'attributes'
                    break
            }

            posthog.capture(event, attributes)
            actions.addProductIntent({
                product_type: ProductKey.LOGS,
                intent_context: ProductIntentContext.LOGS_SET_FILTERS,
            })
        },
    })),

    subscriptions(({ props, values }) => ({
        filters: (filters: LogsViewerFilters, oldFilters: LogsViewerFilters) => {
            if (objectsEqual(filters, oldFilters)) {
                return
            }
            props.onFiltersChanged?.(filters)
            props.onConfigChanged?.(values.config)
        },
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (oldProps?.config && !objectsEqual(props.config.filters, oldProps.config.filters)) {
            actions.setFilters(props.config.filters)
        }
    }),
])
