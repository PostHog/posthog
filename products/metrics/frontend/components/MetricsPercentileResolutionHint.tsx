import posthog from 'posthog-js'
import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonBanner, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { formatMetricValue } from '../panels/metricsUnits'
import { coarsePercentileResolution, customBucketSnippet, suggestedBucketEdges } from './metricsPercentileResolution'
import type { MetricsViewerSeries } from './metricsViewerLogic'

const EXPONENTIAL_ENV = 'OTEL_EXPORTER_OTLP_METRICS_DEFAULT_HISTOGRAM_AGGREGATION=base2_exponential_bucket_histogram'

/** Warns that the percentile lines snap between a few wide buckets, and shows how to get sharper ones. */
export function MetricsPercentileResolutionHint({
    series,
    metricName,
}: {
    series: MetricsViewerSeries[]
    metricName: string | null
}): JSX.Element | null {
    const [guideOpen, setGuideOpen] = useState(false)
    const resolution = useMemo(() => coarsePercentileResolution(series), [series])
    const unit = series.find((s) => s.histogram_bounds?.length)?.unit ?? undefined
    const suggested = useMemo(
        () =>
            suggestedBucketEdges(
                series.flatMap((s) => (s.histogram_bounds?.length ? s.points.map((p) => p.value ?? 0) : []))
            ),
        [series]
    )

    // Live refresh reruns the query every few seconds, so count one view per metric.
    const reportedMetric = useRef<string | null>(null)
    useEffect(() => {
        if (resolution && reportedMetric.current !== metricName) {
            reportedMetric.current = metricName
            posthog.capture('metrics percentile resolution hint shown', { edge_count: resolution.edges.length })
        }
    }, [resolution, metricName])

    if (!resolution) {
        return null
    }
    const format = (value: number): string => formatMetricValue(value, unit)
    const bucket =
        resolution.upper === Infinity
            ? `above ${format(resolution.lower)}`
            : resolution.lower <= 0
              ? `below ${format(resolution.upper)}`
              : `between ${format(resolution.lower)} and ${format(resolution.upper)}`
    const metric = metricName ?? 'your_histogram'

    return (
        <>
            <LemonBanner
                type="info"
                className="mt-2"
                data-attr="metrics-percentile-resolution-hint"
                action={{
                    children: 'Get sharper percentiles',
                    onClick: () => {
                        setGuideOpen(true)
                        posthog.capture('metrics percentile resolution guide opened')
                    },
                }}
            >
                <div>
                    These percentiles are estimates from {resolution.edges.length} bucket edges. Most points are{' '}
                    <strong>{bucket}</strong>, and the lines can only move between these edges:{' '}
                    {resolution.edges.map(format).join(' · ')}.
                </div>
            </LemonBanner>
            <LemonModal
                isOpen={guideOpen}
                onClose={() => setGuideOpen(false)}
                title="Get sharper percentiles"
                description="Percentiles are interpolated inside the bucket that holds them. Narrower buckets give lines you can trust. Change one service or endpoint at a time: series with different buckets still chart together."
                width={720}
            >
                <div className="flex flex-col gap-6">
                    <section className="flex flex-col gap-2">
                        <div className="flex items-center gap-2">
                            <h4 className="m-0">Exponential histograms</h4>
                            <LemonTag type="success">Recommended</LemonTag>
                        </div>
                        <p className="m-0 text-secondary">
                            The SDK picks the buckets for each series, so every endpoint gets about 5% precision, fast
                            or slow. There is no bucket list to keep up to date. Set one environment variable on any
                            OpenTelemetry SDK:
                        </p>
                        <CodeSnippet
                            language={Language.Bash}
                            wrap
                            onCopy={() =>
                                posthog.capture('metrics percentile resolution snippet copied', {
                                    option: 'exponential',
                                })
                            }
                        >
                            {EXPONENTIAL_ENV}
                        </CodeSnippet>
                    </section>
                    <section className="flex flex-col gap-2">
                        <h4 className="m-0">Custom buckets for one histogram</h4>
                        <p className="m-0 text-secondary">
                            Use this when you must keep a classic histogram, for example with a Prometheus client. These
                            edges cover what this chart shows:
                        </p>
                        <CodeSnippet
                            language={Language.Python}
                            wrap
                            onCopy={() =>
                                posthog.capture('metrics percentile resolution snippet copied', { option: 'custom' })
                            }
                        >
                            {customBucketSnippet(metric, unit ?? 's', suggested)}
                        </CodeSnippet>
                    </section>
                </div>
            </LemonModal>
        </>
    )
}
