import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { Chart } from 'lib/Chart'
import { useChart } from 'lib/hooks/useChart'
import { urls } from 'scenes/urls'

import { clustersLogic } from './clustersLogic'
import { TraceSummary } from './types'

interface ScatterPoint {
    x: number
    y: number
    traceId?: string
    clusterId?: number
    timestamp?: string
}

interface ClusterScatterPlotProps {
    traceSummaries: Record<string, TraceSummary>
}

export function ClusterScatterPlot({ traceSummaries }: ClusterScatterPlotProps): JSX.Element {
    const { scatterPlotDatasets, traceToClusterTitle, sortedClusters, effectiveRunId } = useValues(clustersLogic)

    const handleClick = (
        _event: MouseEvent,
        elements: { datasetIndex: number; index: number }[],
        chart: Chart<'scatter'>
    ): void => {
        if (elements.length === 0) {
            return
        }

        const element = elements[0]
        const dataset = chart.data?.datasets?.[element.datasetIndex]
        if (!dataset) {
            return
        }

        const point = dataset.data?.[element.index] as ScatterPoint | undefined

        // Navigate to cluster page for centroid clicks
        if (dataset.label?.includes('(centroid)')) {
            if (point?.clusterId !== undefined && effectiveRunId) {
                router.actions.push(urls.llmAnalyticsCluster(effectiveRunId, point.clusterId))
            }
            return
        }

        // Navigate to trace page for trace clicks
        if (point?.traceId) {
            router.actions.push(
                urls.llmAnalyticsTrace(point.traceId, {
                    tab: 'summary',
                    ...(point.timestamp ? { timestamp: point.timestamp } : {}),
                })
            )
        }
    }

    const { canvasRef, chartRef } = useChart<'scatter'>({
        getConfig: () => {
            if (scatterPlotDatasets.length === 0) {
                return null
            }

            return {
                type: 'scatter',
                data: { datasets: scatterPlotDatasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    // Chart.js onClick type is complex; cast through unknown for type safety
                    onClick: handleClick as unknown as undefined,
                    onHover: (event, elements) => {
                        const canvas = event.native?.target as HTMLCanvasElement | undefined
                        if (canvas) {
                            // Show pointer cursor for all clickable points (traces and centroids)
                            canvas.style.cursor = elements.length > 0 ? 'pointer' : 'default'
                        }
                    },
                    plugins: {
                        legend: {
                            display: false,
                        },
                        zoom: {
                            zoom: {
                                drag: {
                                    enabled: true,
                                    backgroundColor: 'rgba(100, 100, 100, 0.3)',
                                    borderColor: 'rgba(100, 100, 100, 0.8)',
                                    borderWidth: 1,
                                },
                                mode: 'xy',
                            },
                        },
                        tooltip: {
                            bodyFont: {
                                weight: 'normal',
                            },
                            footerFont: {
                                weight: 'normal',
                                style: 'italic',
                            },
                            callbacks: {
                                title: (context) => {
                                    const datasetLabel = context[0]?.dataset?.label || ''
                                    return datasetLabel.replace(' (centroid)', '')
                                },
                                label: (context) => {
                                    const isCentroid = context.dataset.label?.includes('(centroid)')
                                    if (isCentroid) {
                                        return 'Cluster centroid'
                                    }

                                    const point = context.raw as ScatterPoint
                                    if (point.traceId) {
                                        const summary = traceSummaries[point.traceId]
                                        if (summary?.title) {
                                            return summary.title
                                        }
                                    }

                                    return undefined
                                },
                                footer: (context) => {
                                    const isCentroid = context[0]?.dataset?.label?.includes('(centroid)')
                                    if (isCentroid) {
                                        return 'click to view cluster'
                                    }

                                    const point = context[0]?.raw as ScatterPoint
                                    if (point?.traceId) {
                                        return 'click to view trace'
                                    }
                                    return ''
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            type: 'linear',
                            position: 'bottom',
                            display: false,
                        },
                        y: {
                            type: 'linear',
                            display: false,
                        },
                    },
                },
            }
        },
        deps: [scatterPlotDatasets, traceSummaries, traceToClusterTitle],
    })

    // Reset zoom on double-click
    useEffect(() => {
        const canvas = canvasRef.current
        if (!canvas) {
            return
        }

        const handleDoubleClick = (): void => {
            if (chartRef.current) {
                // resetZoom is added by chartjs-plugin-zoom at runtime
                ;(chartRef.current as unknown as { resetZoom: () => void }).resetZoom()
            }
        }

        canvas.addEventListener('dblclick', handleDoubleClick)
        return () => canvas.removeEventListener('dblclick', handleDoubleClick)
    }, [canvasRef, chartRef])

    if (sortedClusters.length === 0) {
        return <div className="text-muted text-center py-8">No cluster data available for visualization</div>
    }

    return (
        <div className="h-80">
            <canvas ref={canvasRef} />
        </div>
    )
}
