import { IconClock, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonDivider, LemonModal, Link, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { VariantTag } from 'scenes/experiments/ExperimentView/VariantTag'
import { ElapsedTime } from 'scenes/experiments/MetricsView/new/ElapsedTime'
import { VariantTimeseriesChart } from 'scenes/experiments/MetricsView/new/VariantTimeseriesChart'
import { MetricTitle } from 'scenes/experiments/MetricsView/shared/MetricTitle'
import { ExperimentVariantResult } from 'scenes/experiments/MetricsView/shared/utils'
import { urls } from 'scenes/urls'

import { ExperimentMetric, isExperimentRatioMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { QuillTimeseriesModal } from './QuillTimeseriesModal'
import {
    TIMESERIES_PROGRESS_HELP,
    TIMESERIES_RECALCULATE_TITLE,
    TIMESERIES_RECALCULATE_WARNING,
    TIMESERIES_STALE_NOTE,
    useTimeseriesModal,
} from './useTimeseriesModal'

interface TimeseriesModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric
    variantResult: ExperimentVariantResult
    experiment: Experiment
}

export function TimeseriesModal({
    isOpen,
    onClose,
    metric,
    variantResult,
    experiment,
}: TimeseriesModalProps): JSX.Element {
    const model = useTimeseriesModal({ isOpen, metric, variantResult, experiment })
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav && resultsRedesign) {
        return (
            <QuillTimeseriesModal
                isOpen={isOpen}
                onClose={onClose}
                metric={metric}
                variantKey={variantResult.key}
                model={model}
            />
        )
    }

    const {
        chartData: processedChartData,
        progressMessage,
        hasTimeseriesData,
        timeseriesLoading,
        isRecalculating,
        recalculationCreatedAt,
        isStaleExperiment,
        recalculate,
        refresh,
    } = model

    const handleRecalculate = (): void => {
        LemonDialog.open({
            title: TIMESERIES_RECALCULATE_TITLE,
            content: (
                <div>
                    <p>{TIMESERIES_RECALCULATE_WARNING}</p>
                </div>
            ),
            primaryButton: {
                children: 'Recalculate',
                type: 'primary',
                onClick: recalculate,
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title={
                <div className="flex items-center gap-2 text-sm min-w-0">
                    <div className="flex items-center shrink-0">
                        <span>Time series</span>
                    </div>
                    <LemonDivider vertical className="h-4 self-stretch shrink-0" />
                    <div className="min-w-0 [&_span]:!line-clamp-1">
                        <MetricTitle metric={metric} />
                    </div>
                    <LemonDivider vertical className="h-4 self-stretch shrink-0" />
                    <div className="flex items-center shrink-0">
                        <VariantTag variantKey={variantResult.key} />
                    </div>
                </div>
            }
            footer={
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <div>
                {timeseriesLoading ? (
                    <div
                        className="flex items-center justify-center gap-2 text-[14px] font-normal"
                        //eslint-disable-next-line react/forbid-dom-props
                        style={{ height: '200px' }}
                    >
                        <Spinner className="text-lg" />
                        <span>Loading timeseries&hellip;</span>
                    </div>
                ) : (
                    <div>
                        {isStaleExperiment && !isRecalculating && (
                            <div className="mb-2">
                                <LemonBanner type="warning">
                                    <div className="flex items-center justify-between">
                                        <div className="flex-1">
                                            <div className="text-sm">{TIMESERIES_STALE_NOTE}</div>
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={handleRecalculate}
                                            className="ml-4"
                                        >
                                            Recalculate
                                        </LemonButton>
                                    </div>
                                </LemonBanner>
                            </div>
                        )}
                        {isRecalculating && (
                            <div className="mb-4">
                                <LemonBanner type="info">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <Spinner className="text-sm" />
                                            <span>
                                                Recalculating • <ElapsedTime startTime={recalculationCreatedAt} />{' '}
                                                elapsed •
                                            </span>
                                            <Link onClick={refresh}>Refresh</Link>
                                        </div>
                                    </div>
                                </LemonBanner>
                            </div>
                        )}
                        <div className="flex justify-between items-center mt-2 mb-4">
                            <div className="flex items-center gap-1">
                                <div className="text-xs text-muted">{progressMessage || ''}</div>
                                {progressMessage && (
                                    <Tooltip title={TIMESERIES_PROGRESS_HELP}>
                                        <IconInfo className="text-muted text-base" />
                                    </Tooltip>
                                )}
                            </div>
                            <More
                                overlay={
                                    <>
                                        <LemonButton onClick={handleRecalculate}>Recalculate</LemonButton>
                                    </>
                                }
                            />
                        </div>
                        {hasTimeseriesData && processedChartData ? (
                            <VariantTimeseriesChart
                                chartData={processedChartData}
                                isRatioMetric={isExperimentRatioMetric(metric)}
                            />
                        ) : (
                            <div className="py-10 text-center text-muted flex flex-col items-center gap-2 max-w-80 mx-auto">
                                <IconClock className="text-2xl" />
                                <div>
                                    Timeseries data is calculated once per day. Check your calculation time in{' '}
                                    <Link to={`${urls.experiments()}?tab=settings`} target="_blank">
                                        settings
                                    </Link>
                                    .
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
