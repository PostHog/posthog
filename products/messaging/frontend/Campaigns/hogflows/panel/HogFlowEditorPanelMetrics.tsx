import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

import { CAMPAIGN_METRICS_INFO } from '../../CampaignMetrics'
import { EXIT_NODE_ID, TRIGGER_NODE_ID } from '../../campaignLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelMetrics(): JSX.Element | null {
    const { selectedNode, campaign } = useValues(hogFlowEditorLogic)
    const { loadActionMetricsById } = useActions(hogFlowEditorLogic)
    const actionId = selectedNode?.data.id
    const id = useMemo(() => {
        return actionId ? ([TRIGGER_NODE_ID, EXIT_NODE_ID].includes(actionId) ? '' : actionId) : undefined
    }, [actionId])

    const logicKey = `hog-flow-metrics-${campaign.id}`

    const metricName = useMemo(() => {
        return actionId === TRIGGER_NODE_ID
            ? ['triggered', 'rate_limited', 'disabled_permanently', 'filtered']
            : actionId === EXIT_NODE_ID
              ? ['succeeded', 'failed']
              : undefined
    }, [actionId])

    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: true,
        forceParams: {
            appSource: 'hog_flow',
            appSourceId: campaign.id,
            instanceId: id,
            breakdownBy: 'metric_name',
            metricName,
        },
    })

    const { appMetricsTrendsLoading, appMetricsTrends, params, currentTeam, getDateRangeAbsolute } = useValues(logic)

    useEffect(() => {
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
                <LemonButton
                    to={urls.messagingCampaign(campaign.id, 'metrics')}
                    size="xsmall"
                    sideIcon={<IconOpenInApp />}
                >
                    Click here to open in full metrics viewer
                </LemonButton>
            </div>
            <div className="p-2 flex flex-col gap-2 overflow-y-auto">
                <div className="flex flex-row gap-2 flex-wrap justify-end">
                    <AppMetricsFilters logicKey={logicKey} />
                </div>

                <div className="relative border rounded min-h-[20rem] bg-white flex flex-1 flex-col">
                    {appMetricsTrendsLoading ? (
                        <div className="flex-1 flex items-center justify-center p-8">
                            <SpinnerOverlay />
                        </div>
                    ) : !appMetricsTrends ? (
                        <div className="flex-1 flex items-center justify-center">
                            <div className="text-muted">No data</div>
                        </div>
                    ) : (
                        <LineGraph
                            className="p-2"
                            xData={{
                                column: {
                                    name: 'date',
                                    type: {
                                        name: 'DATE',
                                        isNumerical: false,
                                    },
                                    label: 'Date',
                                    dataIndex: 0,
                                },
                                data: appMetricsTrends.labels,
                            }}
                            yData={appMetricsTrends.series.map((x) => ({
                                column: {
                                    name: x.name,
                                    type: { name: 'INTEGER', isNumerical: true },
                                    label: x.name,
                                    dataIndex: 0,
                                },
                                settings: {
                                    display: {
                                        color: CAMPAIGN_METRICS_INFO[x.name]?.color,
                                    },
                                },
                                data: x.values,
                            }))}
                            visualizationType={ChartDisplayType.ActionsLineGraph}
                            chartSettings={{
                                showLegend: true,
                                showTotalRow: false,
                            }}
                        />
                    )}
                </div>
            </div>
        </>
    )
}
