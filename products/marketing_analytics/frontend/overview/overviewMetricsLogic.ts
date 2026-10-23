import { LogicWrapper, MakeLogicType, actions, kea, key, path, props, reducers } from 'kea'

import { buildTeamScopedPersistenceConfig } from 'lib/logic/persistence'

import {
    OverviewMetricConfiguration,
    OverviewMetricGroup,
    OverviewMetricGroupConfiguration,
    defaultOverviewMetricConfiguration,
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
])
