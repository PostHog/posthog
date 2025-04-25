import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    CurrencyCode,
    DataTableNode,
    NodeKind,
    RevenueAnalyticsConfig,
    RevenueAnalyticsEventItem,
    RevenueCurrencyPropertyConfig,
} from '~/queries/schema/schema-general'
import { ExternalDataSource, Region } from '~/types'

import type { revenueEventsSettingsLogicType } from './revenueEventsSettingsLogicType'

const createEmptyConfig = (region: Region | null | undefined): RevenueAnalyticsConfig => ({
    events: [],

    // Region won't be always set because we might mount this before we mount preflightLogic
    // so we default to USD if we can't determine the region
    base_currency: region === Region.EU ? CurrencyCode.EUR : CurrencyCode.USD,
})

export const revenueEventsSettingsLogic = kea<revenueEventsSettingsLogicType>([
    path(['scenes', 'data-management', 'revenue', 'revenueEventsSettingsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam', 'currentTeamId'],
            preflightLogic,
            ['preflight'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseSources'],
        ],
        actions: [teamLogic, ['updateCurrentTeam'], dataWarehouseSettingsLogic, ['updateSource']],
    })),
    actions({
        updateBaseCurrency: (baseCurrency: CurrencyCode) => ({ baseCurrency }),

        addEvent: (eventName: string) => ({ eventName }),
        deleteEvent: (eventName: string) => ({ eventName }),
        updateEventRevenueProperty: (eventName: string, revenueProperty: string) => ({ eventName, revenueProperty }),
        updateEventRevenueCurrencyProperty: (
            eventName: string,
            revenueCurrencyProperty: RevenueCurrencyPropertyConfig
        ) => ({
            eventName,
            revenueCurrencyProperty,
        }),

        resetConfig: true,
    }),
    reducers(({ values }) => ({
        revenueAnalyticsConfig: [
            null as RevenueAnalyticsConfig | null,
            {
                updateBaseCurrency: (state: RevenueAnalyticsConfig | null, { baseCurrency }) => {
                    if (!state) {
                        return state
                    }

                    return { ...state, base_currency: baseCurrency }
                },
                addEvent: (state: RevenueAnalyticsConfig | null, { eventName }) => {
                    if (
                        !state ||
                        !eventName ||
                        typeof eventName !== 'string' ||
                        eventName == '$pageview' ||
                        eventName == '$autocapture'
                    ) {
                        return state
                    }

                    const existingEvents = new Set(
                        state.events.map((item: RevenueAnalyticsEventItem) => item.eventName)
                    )
                    if (existingEvents.has(eventName)) {
                        return state
                    }

                    return {
                        ...state,
                        events: [
                            ...state.events,
                            {
                                eventName,
                                revenueProperty: 'revenue',
                                revenueCurrencyProperty: { static: state.base_currency },
                            },
                        ],
                    }
                },
                deleteEvent: (state: RevenueAnalyticsConfig | null, { eventName }) => {
                    if (!state) {
                        return state
                    }
                    return { ...state, events: state.events.filter((item) => item.eventName !== eventName) }
                },
                updateEventRevenueProperty: (state: RevenueAnalyticsConfig | null, { eventName, revenueProperty }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        events: state.events.map((item) => {
                            if (item.eventName === eventName) {
                                return { ...item, revenueProperty }
                            }
                            return item
                        }),
                    }
                },
                updateEventRevenueCurrencyProperty: (
                    state: RevenueAnalyticsConfig | null,
                    { eventName, revenueCurrencyProperty }
                ) => {
                    if (!state) {
                        return state
                    }

                    return {
                        ...state,
                        events: state.events.map((item) => {
                            if (item.eventName === eventName) {
                                return { ...item, revenueCurrencyProperty }
                            }
                            return item
                        }),
                    }
                },
                resetConfig: () => {
                    return values.savedRevenueAnalyticsConfig
                },
                updateCurrentTeam: (_, { revenue_analytics_config }) => {
                    // TODO: Check how to pass the preflight region here
                    return revenue_analytics_config || createEmptyConfig(null)
                },
            },
        ],
        savedRevenueAnalyticsConfig: [
            // TODO: Check how to pass the preflight region here
            values.currentTeam?.revenue_analytics_config || createEmptyConfig(null),
            {
                updateCurrentTeam: (_, { revenue_analytics_config }) => {
                    // TODO: Check how to pass the preflight region here
                    return revenue_analytics_config || createEmptyConfig(null)
                },
            },
        ],
    })),
    selectors({
        baseCurrency: [
            (s) => [s.revenueAnalyticsConfig],
            (revenueAnalyticsConfig: RevenueAnalyticsConfig | null) =>
                revenueAnalyticsConfig?.base_currency || CurrencyCode.USD,
        ],

        events: [
            (s) => [s.revenueAnalyticsConfig],
            (revenueAnalyticsConfig: RevenueAnalyticsConfig | null) => revenueAnalyticsConfig?.events || [],
        ],
        changesMadeToEvents: [
            (s) => [s.revenueAnalyticsConfig, s.savedRevenueAnalyticsConfig],
            (config, savedConfig): boolean => {
                return !!config && !objectsEqual(config.events, savedConfig.events)
            },
        ],

        saveEventsDisabledReason: [
            (s) => [s.revenueAnalyticsConfig, s.changesMadeToEvents],
            (config, changesMade): string | null => {
                if (!config) {
                    return 'Loading...'
                }
                if (!changesMade) {
                    return 'No changes to save'
                }
                return null
            },
        ],

        enabledDataWarehouseSources: [
            (s) => [s.dataWarehouseSources],
            (dataWarehouseSources: ExternalDataSource[]): ExternalDataSource[] => {
                return dataWarehouseSources?.filter((source) => source.revenue_analytics_enabled) ?? []
            },
        ],

        exampleEventsQuery: [
            (s) => [s.savedRevenueAnalyticsConfig],
            (revenueAnalyticsConfig: RevenueAnalyticsConfig | null) => {
                if (!revenueAnalyticsConfig) {
                    return null
                }

                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    full: true,
                    showPropertyFilter: false,
                    source: {
                        kind: NodeKind.RevenueExampleEventsQuery,
                    },
                }

                return query
            },
        ],
        exampleDataWarehouseTablesQuery: [
            (s) => [s.savedRevenueAnalyticsConfig],
            (revenueAnalyticsConfig: RevenueAnalyticsConfig | null) => {
                if (!revenueAnalyticsConfig) {
                    return null
                }

                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    full: true,
                    showPropertyFilter: false,
                    source: {
                        kind: NodeKind.RevenueExampleDataWarehouseTablesQuery,
                    },
                }

                return query
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        saveChanges: {
            save: () => {
                actions.updateCurrentTeam({
                    revenue_analytics_config:
                        values.revenueAnalyticsConfig || createEmptyConfig(values.preflight?.region),
                })
                return null
            },
        },
        revenueAnalyticsConfig: {
            loadRevenueAnalyticsConfig: async () => {
                if (values.currentTeam) {
                    return values.currentTeam.revenue_analytics_config || createEmptyConfig(values.preflight?.region)
                }
                return null
            },
        },
    })),
    beforeUnload(({ actions, values }) => ({
        enabled: () => values.changesMadeToEvents,
        message: 'Changes you made will be discarded. Make sure you save your changes before leaving this page.',
        onConfirm: () => {
            actions.resetConfig()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRevenueAnalyticsConfig()
    }),
])
