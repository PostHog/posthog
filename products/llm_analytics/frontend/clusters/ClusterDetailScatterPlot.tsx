import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { Chart } from 'lib/Chart'
import { useChart } from 'lib/hooks/useChart'
import { urls } from 'scenes/urls'

import { clusterDetailLogic } from './clusterDetailLogic'

interface ScatterPoint {
    x: number
    y: number
    traceId?: string
    timestamp?: string
}

export function ClusterDetailScatterPlot(): JSX.Element {
    const { cluster, traceSummaries, scatterPlotDatasets } = useValues(clusterDetailLogic)

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
            if (!cluster || scatterPlotDatasets.length === 0) {
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
                    onHover: (event, elements, chart) => {
                        const canvas = event.native?.target as HTMLCanvasElement | undefined
                        if (canvas) {
                            const dataset = chart?.data?.datasets?.[elements[0]?.datasetIndex]
                            const isCentroid = elements.length > 0 && dataset?.label === 'Centroid'
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
        deps: [scatterPlotDatasets, traceSummaries, cluster],
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

    return (
        <div className="h-64">
            <canvas ref={canvasRef} />
        </div>
    )
}
