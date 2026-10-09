import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ExperimentVariantsReadoutApi } from '../../../generated/api.schemas'
import type { VariantComparisonState } from '../../scannerVariantsLogic'

export interface VariantAnalysisRunNow {
    onClick: () => void
    /** The request to start a run is in flight. */
    loading: boolean
    running: boolean
    disabledReason: string | null
}

export interface VariantDifferencesCardProps {
    readout: ExperimentVariantsReadoutApi
    comparisonState: VariantComparisonState
    /** Why the person can't set up the scout, or undefined when they can. */
    setupDisabledReason?: string | null
    onSetUp: () => void
    /** Opens the existing variant analysis scout; undefined when it isn't loaded. */
    onOpenScout?: () => void
    /** Starts the variant analysis scout now; undefined when there is no scout. */
    runNow?: VariantAnalysisRunNow
}

/** The comparison between variants, which the variant analysis scout records once a day. */
export function VariantDifferencesCard({
    readout,
    comparisonState,
    setupDisabledReason,
    onSetUp,
    onOpenScout,
    runNow,
}: VariantDifferencesCardProps): JSX.Element {
    const scoutPaused = readout.analysis?.scout_enabled === false
    const openScoutButton = onOpenScout ? (
        <LemonButton type="secondary" size="small" onClick={onOpenScout} data-attr="vision-variants-open-scout">
            Open scout
        </LemonButton>
    ) : null
    const runNowButton = runNow ? (
        <LemonButton
            type="secondary"
            size="small"
            onClick={runNow.onClick}
            loading={runNow.loading}
            disabledReason={runNow.disabledReason ?? undefined}
            tooltip="Run variant analysis now instead of waiting for its next scheduled run. You can run it once an hour."
            data-attr="vision-variants-run-analysis"
        >
            {runNow.running ? 'Running…' : 'Run now'}
        </LemonButton>
    ) : null

    if (comparisonState === 'no_scout') {
        return (
            <LemonCard hoverEffect={false} className="p-4 flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                    <h3 className="m-0 text-base font-semibold">Compare what people do in each variant</h3>
                    <p className="m-0 text-sm text-muted">
                        Variant analysis is a scout that reads each variant's summaries once a day and records what
                        differs between them. Each run uses credits.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    onClick={onSetUp}
                    disabledReason={setupDisabledReason ?? undefined}
                    data-attr="vision-variants-set-up-analysis"
                >
                    Set up variant analysis
                </LemonButton>
            </LemonCard>
        )
    }

    if (comparisonState === 'pending' || comparisonState === 'updating') {
        return (
            <LemonCard hoverEffect={false} className="p-4 flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                    <h3 className="m-0 text-base font-semibold">What differs between variants</h3>
                    <p className="m-0 text-sm text-muted">
                        {comparisonState === 'pending'
                            ? 'The first analysis arrives after the next run. The scout runs once a day, at 9:00 by default.'
                            : 'The scanner changed since the last analysis, so the comparison updates after the next run.'}
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {runNowButton}
                    {openScoutButton}
                </div>
            </LemonCard>
        )
    }

    const differences = readout.differences ?? []
    const analysisCount = (key: string): number | null =>
        readout.variants.find((variant) => variant.key === key)?.analysis_observations ?? null

    return (
        <LemonCard hoverEffect={false} className="p-4 space-y-3" data-attr="vision-variants-differences">
            {scoutPaused && (
                <LemonBanner
                    type="warning"
                    action={onOpenScout ? { children: 'Open scout', onClick: onOpenScout } : undefined}
                >
                    Variant analysis is paused, so this comparison doesn't update.
                </LemonBanner>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="m-0 text-base font-semibold">What differs between variants</h3>
                <div className="flex items-center gap-2">
                    {readout.analysis?.recorded_at && (
                        <span className="text-xs text-muted">
                            Updated <TZLabel time={readout.analysis.recorded_at} />
                        </span>
                    )}
                    {runNowButton}
                </div>
            </div>
            <div className="flex flex-col gap-4 @3xl:flex-row">
                {differences.length > 0 ? (
                    <ul className="m-0 min-w-0 flex-1 list-disc space-y-2 pl-5">
                        {differences.map((difference) => (
                            <li key={difference.theme} className="text-sm">
                                <span>{difference.statement}</span>{' '}
                                <span className="text-muted">
                                    {`(${Object.entries(difference.counts)
                                        .map(([key, count]) => {
                                            const outOf = analysisCount(key)
                                            return outOf != null ? `${key} ${count} of ${outOf}` : `${key} ${count}`
                                        })
                                        .join(', ')})`}
                                </span>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="m-0 min-w-0 flex-1 text-sm text-muted">
                        The latest analysis found no clear difference between variants.
                    </p>
                )}
                <p className="m-0 text-xs text-muted @3xl:max-w-64 @3xl:border-l @3xl:pl-4">
                    Counts come from the model's summaries, not from tracked events. Samples are small, so treat a
                    difference under about 10 observations as a lead to check, not a result.
                </p>
            </div>
        </LemonCard>
    )
}
