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
    RevenueCurrencyPropertyConfig,
    RevenueTrackingConfig,
    RevenueTrackingEventItem,
} from '~/queries/schema/schema-general'
import { ExternalDataSource, Region } from '~/types'

import type { revenueEventsSettingsLogicType } from './revenueEventsSettingsLogicType'

const createEmptyConfig = (region: Region | null | undefined): RevenueTrackingConfig => ({
    events: [],

    // Region won't be always set because we might mount this before we mount preflightLogic
    // so we default to USD if we can't determine the region
    baseCurrency: region === Region.EU ? CurrencyCode.EUR : CurrencyCode.USD,
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
        revenueTrackingConfig: [
            null as RevenueTrackingConfig | null,
            {
                updateBaseCurrency: (state, { baseCurrency }) => {
                    if (!state) {
                        return state
                    }

                    return { ...state, baseCurrency }
                },
                addEvent: (state, { eventName }) => {
                    if (
                        !state ||
                        !eventName ||
                        typeof eventName !== 'string' ||
                        eventName == '$pageview' ||
                        eventName == '$autocapture'
                    ) {
                        return state
                    }

                    const existingEvents = new Set(state.events.map((item: RevenueTrackingEventItem) => item.eventName))
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
                                revenueCurrencyProperty: { static: state.baseCurrency },
                            },
                        ],
                    }
                },
                deleteEvent: (state, { eventName }) => {
                    if (!state) {
                        return state
                    }
                    return { ...state, events: state.events.filter((item) => item.eventName !== eventName) }
                },
                updateEventRevenueProperty: (state, { eventName, revenueProperty }) => {
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
                updateEventRevenueCurrencyProperty: (state, { eventName, revenueCurrencyProperty }) => {
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
                    return values.savedRevenueTrackingConfig
                },
                updateCurrentTeam: (_, { revenue_tracking_config }) => {
                    // TODO: Check how to pass the preflight region here
                    return revenue_tracking_config || createEmptyConfig(null)
                },
            },
        ],
        savedRevenueTrackingConfig: [
            // TODO: Check how to pass the preflight region here
            values.currentTeam?.revenue_tracking_config || createEmptyConfig(null),
            {
                updateCurrentTeam: (_, { revenue_tracking_config }) => {
                    // TODO: Check how to pass the preflight region here
                    return revenue_tracking_config || createEmptyConfig(null)
                },
            },
        ],
    })),
    selectors({
        baseCurrency: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) =>
                revenueTrackingConfig?.baseCurrency || CurrencyCode.USD,
        ],

        events: [
            (s) => [s.revenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => revenueTrackingConfig?.events || [],
        ],
        changesMadeToEvents: [
            (s) => [s.revenueTrackingConfig, s.savedRevenueTrackingConfig],
            (config, savedConfig): boolean => {
                return !!config && !objectsEqual(config.events, savedConfig.events)
            },
        ],

        saveEventsDisabledReason: [
            (s) => [s.revenueTrackingConfig, s.changesMadeToEvents],
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
            (s) => [s.savedRevenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => {
                if (!revenueTrackingConfig) {
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
            (s) => [s.savedRevenueTrackingConfig],
            (revenueTrackingConfig: RevenueTrackingConfig | null) => {
                if (!revenueTrackingConfig) {
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
                    revenue_tracking_config:
                        values.revenueTrackingConfig || createEmptyConfig(values.preflight?.region),
                })
                return null
            },
        },
        revenueTrackingConfig: {
            loadRevenueTrackingConfig: async () => {
                if (values.currentTeam) {
                    return values.currentTeam.revenue_tracking_config || createEmptyConfig(values.preflight?.region)
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
        actions.loadRevenueTrackingConfig()
    }),
])
