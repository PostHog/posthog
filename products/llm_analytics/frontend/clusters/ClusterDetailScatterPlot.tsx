import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { Chart } from 'lib/Chart'
import { useChart } from 'lib/hooks/useChart'
import { urls } from 'scenes/urls'

import { clusterDetailLogic } from './clusterDetailLogic'
import { isCentroidDataset } from './constants'
import { formatEvalTitle } from './traceSummaryLoader'

interface ScatterPoint {
    x: number
    y: number
    traceId?: string
    generationId?: string
    timestamp?: string
}

export function ClusterDetailScatterPlot(): JSX.Element {
    const { cluster, traceSummaries, scatterPlotDatasets, clusteringLevel } = useValues(clusterDetailLogic)

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
        if (!dataset || isCentroidDataset(dataset)) {
            return
        }

        const point = dataset.data?.[element.index] as ScatterPoint | undefined
        if (!point) {
            return
        }

        if (clusteringLevel === 'evaluation') {
            // For eval points, point.traceId is the backend's eval-uuid fallback
            // when the metadata join couldn't resolve — routing to /traces/<eval_uuid>
            // 404s. Use the loaded summary's real traceId instead; if it hasn't
            // loaded yet we just no-op (the list below shows "Loading...").
            const summary = point.generationId ? traceSummaries[point.generationId] : undefined
            const resolvedTraceId = summary?.traceId
            if (!resolvedTraceId) {
                return
            }
            router.actions.push(
                urls.llmAnalyticsTrace(resolvedTraceId, {
                    tab: 'summary',
                    ...(point.generationId ? { event: point.generationId } : {}),
                    ...(point.timestamp ? { timestamp: point.timestamp } : {}),
                })
            )
            return
        }

        if (point.traceId) {
            router.actions.push(
                urls.llmAnalyticsTrace(point.traceId, {
                    tab: 'summary',
                    // For generation-level, highlight the specific generation
                    ...(clusteringLevel === 'generation' && point.generationId ? { event: point.generationId } : {}),
                    // timestamp is the trace's first_timestamp for both levels
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
                        if (!canvas) {
                            return
                        }
                        if (elements.length === 0) {
                            canvas.style.cursor = 'default'
                            return
                        }
                        const element = elements[0]
                        const dataset = chart?.data?.datasets?.[element.datasetIndex]
                        if (isCentroidDataset(dataset)) {
                            canvas.style.cursor = 'default'
                            return
                        }
                        // Eval points are only clickable once their summary has loaded —
                        // otherwise point.traceId is the backend's eval-uuid fallback
                        // and the click would 404. Mirror the logic in handleClick.
                        if (clusteringLevel === 'evaluation') {
                            const point = dataset?.data?.[element.index] as ScatterPoint | undefined
                            const summary = point?.generationId ? traceSummaries[point.generationId] : undefined
                            canvas.style.cursor = summary?.traceId ? 'pointer' : 'default'
                            return
                        }
                        canvas.style.cursor = 'pointer'
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
                                    const isCentroid = isCentroidDataset(context[0]?.dataset)
                                    if (isCentroid) {
                                        return 'Cluster centroid'
                                    }
                                    return cluster.title
                                },
                                label: (context) => {
                                    const isCentroid = isCentroidDataset(context.dataset)
                                    if (isCentroid) {
                                        return 'Center of this cluster'
                                    }

                                    const point = context.raw as ScatterPoint
                                    // For evaluation-level, the cluster item id (= eval uuid) is
                                    // carried in generationId; traceId is the parent trace being
                                    // judged, which doesn't key into the summary map.
                                    // For generation-level, summaries are keyed by generation_id.
                                    // For trace-level, summaries are keyed by trace_id.
                                    const summaryKey =
                                        clusteringLevel === 'generation' || clusteringLevel === 'evaluation'
                                            ? point.generationId
                                            : point.traceId
                                    if (summaryKey) {
                                        const summary = traceSummaries[summaryKey]
                                        if (clusteringLevel === 'evaluation') {
                                            const formatted = formatEvalTitle(summary, 140)
                                            if (formatted) {
                                                return formatted
                                            }
                                        } else if (summary?.title) {
                                            return summary.title
                                        }
                                    }
                                    if (point.traceId) {
                                        return clusteringLevel === 'generation'
                                            ? `Generation ${(point.generationId || point.traceId).slice(0, 8)}...`
                                            : clusteringLevel === 'evaluation'
                                              ? `Evaluation ${(point.generationId || point.traceId).slice(0, 8)}...`
                                              : `Trace ${point.traceId.slice(0, 8)}...`
                                    }
                                    return undefined
                                },
                                footer: (context) => {
                                    const isCentroid = isCentroidDataset(context[0]?.dataset)
                                    if (isCentroid) {
                                        return ''
                                    }
                                    const point = context[0]?.raw as ScatterPoint
                                    if (point?.traceId) {
                                        return clusteringLevel === 'generation' || clusteringLevel === 'evaluation'
                                            ? 'click to view generation'
                                            : 'click to view trace'
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
