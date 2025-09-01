import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelMetricsDetail(): JSX.Element | null {
    const { selectedNode, campaign } = useValues(hogFlowEditorLogic)
    const id = selectedNode?.data.id ?? 'unknown'

    const logicKey = `hog-flow-metrics-${id}`

    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: true,
        forceParams: {
            appSource: 'hog_flow',
            appSourceId: campaign.id,
            instanceId: id,
            // metricName: ['succeeded', 'failed', 'filtered', 'disabled_permanently'],
            breakdownBy: 'metric_name',
        },
    })

    const { appMetricsTrendsLoading, appMetricsTrends } = useValues(logic)
    const { loadAppMetricsTrends } = useActions(logic)

    useEffect(() => {
        loadAppMetricsTrends()
    }, [loadAppMetricsTrends])

    return (
        <div className="p-2 flex flex-col gap-2 overflow-hidden">
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
                            data: x.values,
                        }))}
                        visualizationType={ChartDisplayType.ActionsLineGraph}
                        chartSettings={{
                            showLegend: true,
                            showTotalRow: true,
                        }}
                    />
                )}
            </div>
        </div>
    )
}
