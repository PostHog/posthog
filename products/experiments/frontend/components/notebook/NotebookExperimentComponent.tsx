import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDiff } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'
import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { MicroChart } from '~/scenes/experiments/ExperimentView/Exposures'
import { isLegacyExperiment, isSavedExperiment } from '~/scenes/experiments/utils'

import { ExperimentStatItem } from './ExperimentStatItem'
import { NotebookExperimentResults } from './NotebookExperimentResults'

export interface NotebookExperimentComponentProps {
    id: number
    expanded: boolean
}

function formatDuration(startDate: string | null | undefined, endDate: string | null | undefined): string {
    if (!startDate) {
        return 'Not started'
    }
    const start = dayjs(startDate)
    const end = endDate ? dayjs(endDate) : dayjs()
    return humanFriendlyDiff(start, end)
}

function formatTotalExposures(exposures: ExperimentExposureQueryResponse | null): string {
    if (!exposures?.total_exposures) {
        return '0'
    }
    const total = Object.values(exposures.total_exposures).reduce((a, b) => a + b, 0)
    return humanFriendlyNumber(total)
}

export function NotebookExperimentComponent({ id, expanded }: NotebookExperimentComponentProps): JSX.Element {
    const {
        experiment,
        experimentLoading,
        experimentMissing,
        isExperimentDraft,
        isExperimentLaunched,
        exposures,
        exposuresLoading,
        variants,
    } = useValues(experimentLogic({ experimentId: id }))

    const { loadExperiment, loadExposures } = useActions(experimentLogic({ experimentId: id }))

    useEffect(() => {
        loadExperiment()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id])

    useEffect(() => {
        if (isExperimentLaunched && experiment && !isLegacyExperiment(experiment)) {
            loadExposures()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isExperimentLaunched, experiment])

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    const isLegacy = experiment && isLegacyExperiment(experiment)
    // The keyed metrics logic needs a saved, launched experiment to fetch results for.
    const showsResults = isExperimentLaunched && !isLegacy && isSavedExperiment(experiment)
    const totalPrimaryMetrics = experiment?.metrics?.length || 0

    return (
        <div>
            <BindLogic logic={experimentLogic} props={{ experimentId: id }}>
                {!expanded ? (
                    <div className="flex flex-wrap items-center gap-2 p-3">
                        {experimentLoading ? (
                            <LemonSkeleton className="h-6 flex-1" />
                        ) : (
                            <>
                                <span className="min-w-48 flex-1 truncate text-xs text-secondary">
                                    {experiment.description || 'No description'}
                                </span>
                                {isExperimentDraft && !isLegacy ? (
                                    <>
                                        <span className="text-xs text-secondary">
                                            {variants.length} {variants.length === 1 ? 'variant' : 'variants'}
                                        </span>
                                        <span className="text-xs text-secondary">
                                            {totalPrimaryMetrics} {totalPrimaryMetrics === 1 ? 'metric' : 'metrics'}
                                        </span>
                                    </>
                                ) : null}
                                {showsResults && <NotebookExperimentResults experiment={experiment} expanded={false} />}
                            </>
                        )}
                    </div>
                ) : null}

                {/* Expanded Content */}
                {expanded && !experimentLoading && (
                    <>
                        {/* Description */}
                        {experiment.description && (
                            <div className="px-3 pt-3 pb-1 text-sm">{experiment.description}</div>
                        )}

                        {/* Legacy experiment warning */}
                        {isLegacy && (
                            <div className="p-3">
                                <LemonBanner type="warning">
                                    <div>
                                        <strong>Legacy experiment</strong>
                                    </div>
                                    <div>
                                        This experiment uses legacy metrics. Results are only available in the full
                                        experiment view.
                                    </div>
                                </LemonBanner>
                            </div>
                        )}

                        {/* Draft state */}
                        {isExperimentDraft && !isLegacy && (
                            <div className="p-3">
                                <div className="text-sm text-muted mb-2">
                                    Experiment is in draft. Launch to start collecting data.
                                </div>
                                <div className="flex gap-4 text-sm text-muted">
                                    <span>{variants.length} variants</span>
                                    <span>{experiment.metrics?.length || 0} metrics</span>
                                </div>
                            </div>
                        )}

                        {/* Launched state with new metrics */}
                        {showsResults && (
                            <div className="p-3 space-y-3">
                                {/* Stats row */}
                                <div className="flex gap-6">
                                    <ExperimentStatItem
                                        label="Duration"
                                        value={formatDuration(experiment.start_date, experiment.end_date)}
                                    />
                                    <ExperimentStatItem
                                        label="Exposures"
                                        value={formatTotalExposures(exposures)}
                                        loading={exposuresLoading}
                                        chart={exposures ? <MicroChart exposures={exposures} /> : undefined}
                                    />
                                    <ExperimentStatItem label="Variants" value={variants.length} />
                                </div>

                                {/* Primary metric results - show most significant metric */}
                                <NotebookExperimentResults experiment={experiment} expanded />
                            </div>
                        )}
                    </>
                )}
            </BindLogic>
        </div>
    )
}
