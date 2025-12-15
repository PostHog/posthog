import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { Chart } from 'lib/Chart'
import { getSeriesColor } from 'lib/colors'
import { useChart } from 'lib/hooks/useChart'
import { urls } from 'scenes/urls'

import { Cluster, NOISE_CLUSTER_ID, TraceSummary } from './types'

interface ScatterPoint {
    x: number
    y: number
    traceId?: string
    timestamp?: string
}

interface ClusterDetailScatterPlotProps {
    cluster: Cluster
    traceSummaries: Record<string, TraceSummary>
}

const OUTLIER_COLOR = '#888888'

export function ClusterDetailScatterPlot({ cluster, traceSummaries }: ClusterDetailScatterPlotProps): JSX.Element {
    const isOutlier = cluster.cluster_id === NOISE_CLUSTER_ID
    const color = isOutlier ? OUTLIER_COLOR : getSeriesColor(cluster.cluster_id)

    const datasets = useMemo(() => {
        const tracePoints = Object.entries(cluster.traces).map(([traceId, traceInfo]) => ({
            x: traceInfo.x,
            y: traceInfo.y,
            traceId,
            timestamp: traceInfo.timestamp,
        }))

        const result: any[] = [
            {
                label: cluster.title,
                data: tracePoints,
                backgroundColor: `${color}80`,
                borderColor: color,
                borderWidth: 1,
                pointRadius: 5,
                pointHoverRadius: 7,
                pointStyle: isOutlier ? 'crossRot' : 'circle',
            },
        ]

        // Add centroid marker for non-outlier clusters
        if (!isOutlier) {
            result.push({
                label: 'Centroid',
                data: [{ x: cluster.centroid_x, y: cluster.centroid_y }],
                backgroundColor: `${color}40`,
                borderColor: color,
                borderWidth: 2,
                pointRadius: 10,
                pointHoverRadius: 12,
                pointStyle: 'circle',
            })
        }

        return result
    }, [cluster, color, isOutlier])

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
        if (!dataset || dataset.label === 'Centroid') {
            return
        }

        const point = dataset.data?.[element.index] as ScatterPoint | undefined
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
            if (datasets.length === 0) {
                return null
            }

            return {
                type: 'scatter',
                data: { datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick: handleClick as any,
                    onHover: (event, elements, chart) => {
                        const canvas = event.native?.target as HTMLCanvasElement | undefined
                        if (canvas) {
                            const isCentroid =
                                elements.length > 0 &&
                                (chart?.data?.datasets?.[elements[0].datasetIndex] as any)?.label === 'Centroid'
                            canvas.style.cursor = elements.length > 0 && !isCentroid ? 'pointer' : 'default'
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
                                    const isCentroid = context[0]?.dataset?.label === 'Centroid'
                                    if (isCentroid) {
                                        return 'Cluster centroid'
                                    }
                                    return cluster.title
                                },
                                label: (context) => {
                                    const isCentroid = context.dataset.label === 'Centroid'
                                    if (isCentroid) {
                                        return 'Center of this cluster'
                                    }

                                    const point = context.raw as ScatterPoint
                                    if (point.traceId) {
                                        const summary = traceSummaries[point.traceId]
                                        if (summary?.title) {
                                            return summary.title
                                        }
                                        return `Trace ${point.traceId.slice(0, 8)}...`
                                    }
                                    return undefined
                                },
                                footer: (context) => {
                                    const isCentroid = context[0]?.dataset?.label === 'Centroid'
                                    if (isCentroid) {
                                        return ''
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
        deps: [datasets, traceSummaries],
    })

    // Reset zoom on double-click
    useEffect(() => {
        const canvas = canvasRef.current
        if (!canvas) {
            return
        }

        const handleDoubleClick = (): void => {
            if (chartRef.current) {
                ;(chartRef.current as any).resetZoom()
            }
        }

        canvas.addEventListener('dblclick', handleDoubleClick)
        return () => canvas.removeEventListener('dblclick', handleDoubleClick)
    }, [canvasRef, chartRef])

    return (
        <div className="h-64">
            <canvas ref={canvasRef} />
        </div>
    )
}
