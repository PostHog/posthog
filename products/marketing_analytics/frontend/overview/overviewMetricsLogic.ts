import { LogicWrapper, MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { buildTeamScopedPersistenceConfig } from 'lib/logic/persistence'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { hiddenOverviewMetricSources } from './overviewMetricConfiguration'

export interface OverviewMetricsLogicProps {
    viewKey: string
}

export interface overviewMetricsLogicValues {
    /** Saved metric keys in display order, or null to use the default selection. */
    selection: string[] | null
    editorOpen: boolean
    draftSelection: string[] | null
}

export interface overviewMetricsLogicActions {
    openEditor: () => void
    closeEditor: () => void
    setDraftSelection: (selection: string[]) => { selection: string[] }
    applySelection: (selection: string[]) => { selection: string[] }
    reportDashboardControlUsed: (section: string, control: string, value?: boolean | string) => void
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
        openEditor: () => ({}),
        closeEditor: () => ({}),
        setDraftSelection: (selection: string[]) => ({ selection }),
        applySelection: (selection: string[]) => ({ selection }),
    }),
    reducers(() => ({
        selection: [
            null as string[] | null,
            buildTeamScopedPersistenceConfig(),
            {
                applySelection: (_, { selection }) => selection,
            },
        ],
        editorOpen: [
            false,
            {
                openEditor: () => true,
                closeEditor: () => false,
                applySelection: () => false,
            },
        ],
        draftSelection: [
            null as string[] | null,
            {
                setDraftSelection: (_, { selection }) => selection,
                openEditor: () => null,
                closeEditor: () => null,
                applySelection: () => null,
            },
        ],
    })),
    listeners(({ actions }) => ({
        applySelection: ({ selection }) => {
            actions.reportDashboardControlUsed(
                'overview',
                'metric_configuration_applied',
                hiddenOverviewMetricSources(selection)
            )
        },
    })),
])
