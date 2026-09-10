import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import {
    AppMetricsSeriesOverride,
    AppMetricsTimeSeriesChart,
} from 'lib/components/AppMetrics/AppMetricsTimeSeriesChart'
import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { EXIT_NODE_ID, TRIGGER_NODE_ID } from '../../workflowLogic'
import { WORKFLOW_METRICS_INFO } from '../../WorkflowMetrics'
import { WORKFLOW_EMAIL_METRICS, WORKFLOW_PUSH_METRICS } from '../../workflowMetricsSummaryLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelMetrics(): JSX.Element | null {
    const { selectedNode, workflow } = useValues(hogFlowEditorLogic)
    const { loadActionMetricsById } = useActions(hogFlowEditorLogic)
    const actionId = selectedNode?.data.id
    const id = useMemo(() => {
        return actionId ? ([TRIGGER_NODE_ID, EXIT_NODE_ID].includes(actionId) ? '' : actionId) : undefined
    }, [actionId])

    const logicKey = `hog-flow-metrics-${workflow.id}`

    const shouldShowActionLevelMetrics = workflow.trigger?.type !== 'batch'

    const selectedAction = workflow.actions.find((action) => action.id === actionId)
    const isEmailAction = selectedAction?.type === 'function_email'
    const isPushAction = selectedAction?.type === 'function_push'

    const metricName = useMemo(() => {
        return actionId === TRIGGER_NODE_ID
            ? ['triggered', 'rate_limited']
            : actionId === EXIT_NODE_ID
              ? ['succeeded', 'failed']
              : isEmailAction
                ? (Object.keys(WORKFLOW_EMAIL_METRICS) as string[])
                : isPushAction
                  ? (Object.keys(WORKFLOW_PUSH_METRICS) as string[])
                  : undefined
    }, [actionId, isEmailAction, isPushAction])

    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: shouldShowActionLevelMetrics,
        loadOnMount: shouldShowActionLevelMetrics,
        forceParams: {
            appSource: 'hog_flow',
            appSourceId: workflow.id,
            instanceId: id,
            breakdownBy: 'metric_name',
            metricName,
        },
    })

    const { appMetricsTrendsLoading, appMetricsTrends, params, currentTeam, getDateRangeAbsolute } = useValues(logic)

    const seriesOverrides = useMemo(() => {
        if (!appMetricsTrends) {
            return undefined
        }
        const colorSource = (
            isEmailAction ? WORKFLOW_EMAIL_METRICS : isPushAction ? WORKFLOW_PUSH_METRICS : WORKFLOW_METRICS_INFO
        ) as Record<string, { name: string; color: string }>
        return Object.fromEntries(
            appMetricsTrends.series.map((x): [string, AppMetricsSeriesOverride] => [
                x.name,
                { label: colorSource[x.name]?.name, color: colorSource[x.name]?.color },
            ])
        )
    }, [appMetricsTrends, isEmailAction, isPushAction])

    useEffect(() => {
        if (!shouldShowActionLevelMetrics) {
            return
        }
        // Bit hacky - we load the values here from the logic as connecting the logics together was weirdly tricky
        loadActionMetricsById(
            {
                appSource: params.appSource,
                appSourceId: params.appSourceId,
                dateFrom: getDateRangeAbsolute().dateFrom.toISOString(),
                dateTo: getDateRangeAbsolute().dateTo.toISOString(),
            },
            currentTeam?.timezone ?? 'UTC'
        )
    }, [
        shouldShowActionLevelMetrics,
        params.appSource,
        params.appSourceId,
        params.dateFrom,
        params.dateTo,
        currentTeam?.timezone,
        loadActionMetricsById,
        getDateRangeAbsolute,
    ])

    return (
        <>
            <div className="border-b">
                <LemonButton to={urls.workflow(workflow.id, 'metrics')} size="xsmall" sideIcon={<IconOpenInApp />}>
                    {shouldShowActionLevelMetrics
                        ? 'Click here to open in full metrics viewer'
                        : 'Click here to open batch workflow metrics tab'}
                </LemonButton>
            </div>
            {shouldShowActionLevelMetrics && (
                <div className="p-2 flex flex-col gap-2 overflow-y-auto">
                    <div className="flex flex-row gap-2 flex-wrap justify-end">
                        <AppMetricsFilters logicKey={logicKey} />
                    </div>

                    <div className="relative border rounded min-h-[20rem] bg-surface-primary flex flex-1 flex-col">
                        {appMetricsTrendsLoading ? (
                            <div className="flex-1 flex items-center justify-center p-8">
                                <SpinnerOverlay />
                            </div>
                        ) : !appMetricsTrends ? (
                            <div className="flex-1 flex items-center justify-center">
                                <div className="text-muted">No data</div>
                            </div>
                        ) : (
                            <AppMetricsTimeSeriesChart
                                className="p-2"
                                timeSeries={appMetricsTrends}
                                seriesOverrides={seriesOverrides}
                                showLegend
                            />
                        )}
                    </div>
                </div>
            )}
        </>
    )
}
