import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, SpinnerOverlay } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { OperationHistogram } from './OperationHistogram'
import { formatDuration, TraceWaterfallView } from './TraceWaterfallView'
import { tracingOperationSceneLogic, type TracingOperationSceneLogicProps } from './tracingOperationSceneLogic'

export const scene: SceneExport<TracingOperationSceneLogicProps> = {
    component: TracingOperationScene,
    logic: tracingOperationSceneLogic,
    paramsToProps: ({ searchParams: { service, name } }) => ({
        serviceName: String(service ?? ''),
        spanName: String(name ?? ''),
    }),
    productKey: ProductKey.TRACING,
}

function StatBlock({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-xs text-muted">{label}</span>
            <span className="font-mono text-sm">{value}</span>
        </div>
    )
}

export function TracingOperationScene(): JSX.Element {
    const {
        serviceName,
        spanName,
        dateRange,
        histogramData,
        rawHistogramLoading,
        durationSelection,
        samples,
        samplesLoading,
        samplesHaveMore,
        sampleIndex,
        currentSample,
        sampleTraceSpans,
        sampleTraceSpansLoading,
        selectedSpanId,
        operationStats,
    } = useValues(tracingOperationSceneLogic)
    const { setDateRange, setDurationSelection, setSampleIndex, selectSpan } = useActions(tracingOperationSceneLogic)

    if (!spanName) {
        return (
            <SceneContent>
                <div className="flex flex-col items-center gap-1 py-16">
                    <span>This link is missing an operation name.</span>
                    <Link to={urls.tracing()}>Back to tracing</Link>
                </div>
            </SceneContent>
        )
    }

    const errorRate = operationStats && operationStats.count > 0 ? operationStats.error_count / operationStats.count : 0

    return (
        <SceneContent>
            <SceneTitleSection
                name={spanName}
                description={serviceName}
                resourceType={{
                    type: 'tracing',
                }}
                forceBackTo={{
                    key: 'tracing',
                    name: 'Tracing',
                    path: urls.tracing(),
                }}
                actions={
                    <DateFilter
                        dateFrom={dateRange.date_from}
                        dateTo={dateRange.date_to}
                        onChange={(date_from, date_to) => setDateRange({ date_from, date_to })}
                    />
                }
            />
            {operationStats && (
                <div className="flex gap-8">
                    <StatBlock label="Requests" value={humanFriendlyNumber(operationStats.count)} />
                    <StatBlock
                        label="Error rate"
                        value={`${(errorRate * 100).toFixed(errorRate > 0 && errorRate < 0.01 ? 2 : 1)}%`}
                    />
                    <StatBlock label="p50" value={formatDuration(operationStats.p50_duration_nano)} />
                    <StatBlock label="p95" value={formatDuration(operationStats.p95_duration_nano)} />
                    <StatBlock label="p99" value={formatDuration(operationStats.p99_duration_nano)} />
                </div>
            )}
            <OperationHistogram
                data={histogramData}
                loading={rawHistogramLoading}
                selection={durationSelection}
                onSelect={setDurationSelection}
                onClear={() => setDurationSelection(null)}
            />
            <SceneDivider />
            {samples.length === 0 && samplesLoading ? (
                <div className="relative min-h-32">
                    <SpinnerOverlay />
                </div>
            ) : samples.length > 0 ? (
                <>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconChevronLeft />}
                            onClick={() => setSampleIndex(sampleIndex - 1)}
                            disabledReason={
                                samplesLoading ? 'Loading samples…' : sampleIndex <= 0 ? 'First sample' : undefined
                            }
                        />
                        <span className="text-sm whitespace-nowrap">
                            {samples.length > 0 ? sampleIndex + 1 : 0} of {samples.length}
                            {samplesHaveMore ? '+' : ''}
                        </span>
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconChevronRight />}
                            onClick={() => setSampleIndex(sampleIndex + 1)}
                            disabledReason={
                                samplesLoading
                                    ? 'Loading samples…'
                                    : sampleIndex >= samples.length - 1
                                      ? 'Last sample'
                                      : undefined
                            }
                        />
                        {currentSample && (
                            <div className="flex items-center gap-2 ml-2 text-sm text-muted">
                                <span>{humanFriendlyDetailedTime(currentSample.timestamp)}</span>
                                <span className="font-mono">{formatDuration(currentSample.duration_nano)}</span>
                                {currentSample.status_code === 2 && <LemonTag type="danger">Error</LemonTag>}
                            </div>
                        )}
                    </div>
                    <div className="relative min-h-96 flex-1">
                        <TraceWaterfallView
                            spans={sampleTraceSpans}
                            selectedSpanId={selectedSpanId}
                            onSpanSelect={selectSpan}
                        />
                        {sampleTraceSpansLoading && <SpinnerOverlay />}
                    </div>
                </>
            ) : (
                <div className="flex flex-col items-center gap-1 py-8 text-muted">
                    <span>No sampled traces in this range</span>
                    {durationSelection && (
                        <LemonButton size="small" type="secondary" onClick={() => setDurationSelection(null)}>
                            Clear selection
                        </LemonButton>
                    )}
                </div>
            )}
        </SceneContent>
    )
}

export default TracingOperationScene
