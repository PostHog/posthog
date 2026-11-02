import { LogicWrapper, MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { buildTeamScopedPersistenceConfig } from 'lib/logic/persistence'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import {
    OverviewMetricConfiguration,
    OverviewMetricGroup,
    OverviewMetricGroupConfiguration,
    defaultOverviewMetricConfiguration,
    hiddenOverviewMetricGroups,
} from './overviewMetricConfiguration'

export interface OverviewMetricsLogicProps {
    viewKey: string
}

export interface overviewMetricsLogicValues {
    configuration: OverviewMetricConfiguration
    draftConfiguration: OverviewMetricConfiguration | null
}

export interface overviewMetricsLogicActions {
    configureMetrics: (configuration: OverviewMetricConfiguration) => { configuration: OverviewMetricConfiguration }
    closeConfiguration: () => void
    applyConfiguration: (configuration: OverviewMetricConfiguration) => { configuration: OverviewMetricConfiguration }
    updateDraftGroup: (
        group: OverviewMetricGroup,
        configuration: Partial<OverviewMetricGroupConfiguration>
    ) => {
        group: OverviewMetricGroup
        configuration: Partial<OverviewMetricGroupConfiguration>
    }
    resetDraft: () => void
    reportDashboardControlUsed: (section: string, control: string, value?: boolean | string) => void
    setGroupCollapsed: (
        group: OverviewMetricGroup,
        collapsed: boolean
    ) => { group: OverviewMetricGroup; collapsed: boolean }
}

export type overviewMetricsLogicType = MakeLogicType<
    overviewMetricsLogicValues,
    overviewMetricsLogicActions,
    OverviewMetricsLogicProps
>

export const overviewMetricsLogic: LogicWrapper<overviewMetricsLogicType> = kea<overviewMetricsLogicType>([
    props({} as OverviewMetricsLogicProps),
    key(({ viewKey }) => viewKey),
    // The path is the storage key for saved metric preferences.
    path((key) => ['products', 'marketingAnalytics', 'overviewMetricsLogic', key]),
    connect(() => ({ actions: [marketingAnalyticsLogic, ['reportDashboardControlUsed']] })),
    actions({
        configureMetrics: (configuration: OverviewMetricConfiguration) => ({ configuration }),
        closeConfiguration: () => ({}),
        applyConfiguration: (configuration: OverviewMetricConfiguration) => ({ configuration }),
        updateDraftGroup: (group: OverviewMetricGroup, configuration: Partial<OverviewMetricGroupConfiguration>) => ({
            group,
            configuration,
        }),
        resetDraft: () => ({}),
        setGroupCollapsed: (group: OverviewMetricGroup, collapsed: boolean) => ({ group, collapsed }),
    }),
    reducers(() => ({
        configuration: [
            defaultOverviewMetricConfiguration(),
            buildTeamScopedPersistenceConfig(),
            {
                applyConfiguration: (_, { configuration }) => configuration,
                setGroupCollapsed: (state, { group, collapsed }) => ({
                    ...state,
                    [group]: { ...state[group], collapsed },
                }),
            },
        ],
        draftConfiguration: [
            null as OverviewMetricConfiguration | null,
            {
                configureMetrics: (_, { configuration }) => configuration,
                closeConfiguration: () => null,
                applyConfiguration: () => null,
                resetDraft: () => defaultOverviewMetricConfiguration(),
                updateDraftGroup: (state, { group, configuration }) =>
                    state ? { ...state, [group]: { ...state[group], ...configuration } } : state,
            },
        ],
    })),
    listeners(({ actions }) => ({
        applyConfiguration: ({ configuration }) => {
            actions.reportDashboardControlUsed(
                'overview',
                'metric_configuration_applied',
                hiddenOverviewMetricGroups(configuration)
            )
        },
    })),
])
