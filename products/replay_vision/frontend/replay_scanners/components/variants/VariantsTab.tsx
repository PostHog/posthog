import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'

import { getReplayVisionEditDisabledReason } from '../../../utils/accessControl'
import { replayScannerLogic } from '../../replayScannerLogic'
import { variantAnalysisScout } from '../../scannerScout'
import { scannerScoutLogic } from '../../scannerScoutLogic'
import {
    UNATTRIBUTED_VARIANT,
    scannerVariantsLogic,
    variantAnalysisRunDisabledReason,
    variantComparisonState,
    variantObservationsUrl,
} from '../../scannerVariantsLogic'
import { ScannerScoutFormModal } from '../ScannerScoutFormModal'
import { VariantCard } from './VariantCard'
import { VariantDifferencesCard } from './VariantDifferencesCard'
import { VariantsExperimentStrip } from './VariantsExperimentStrip'

export interface VariantsTabProps {
    scannerId: string
}

/** An experiment scanner's readout: what differs between variants first, then each variant side by side. */
export function VariantsTab({ scannerId }: VariantsTabProps): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const scannerName = scanner?.name || ''
    const scoutLogic = scannerScoutLogic({ scannerId, scannerName })
    const { scoutConfigsForScanner, createTemplateKey, settingsSkillName, rollups } = useValues(scoutLogic)
    const { openCreateModal, openScoutSettings } = useActions(scoutLogic)
    const logic = scannerVariantsLogic({ scannerId })
    const { readout, readoutLoading, readoutFailed, variantColors, analysisRunStarting, analysisRunRequest } =
        useValues(logic)
    const { loadReadout, setupAnalysisClicked, variantObservationsOpened, runAnalysisNow } = useActions(logic)

    if (!readout) {
        if (readoutFailed && !readoutLoading) {
            return (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadReadout() }}>
                    Couldn't load the variants. Try again, or open the observations list.
                </LemonBanner>
            )
        }
        return (
            <div className="flex flex-col gap-4">
                <LemonSkeleton className="h-14 w-full" />
                <LemonSkeleton className="h-24 w-full" />
                <LemonSkeleton className="h-64 w-full" />
            </div>
        )
    }

    const existingScout = variantAnalysisScout(scoutConfigsForScanner)
    const comparisonState = variantComparisonState(readout.analysis, !!existingScout)
    const balanced = scanner?.scanner_type !== 'experiment' || scanner.scanner_config.balance_variants !== false
    // Themes come from the variant analysis scout, so without a running one each card says how to get them.
    const themesHint =
        comparisonState === 'no_scout'
            ? 'Set up variant analysis above to see themes here.'
            : readout.analysis?.scout_enabled === false || existingScout?.enabled === false
              ? 'Variant analysis is paused. Turn it on in the scout settings above to see themes here.'
              : null
    const analysisRollup = existingScout ? rollups.get(existingScout.skill_name) : undefined
    const analysisRunning = !!analysisRollup?.runningRun || !!analysisRunRequest
    const runNow = existingScout
        ? {
              onClick: () => runAnalysisNow(existingScout.id, existingScout.skill_name),
              loading: analysisRunStarting,
              running: analysisRunning,
              disabledReason:
                  getReplayVisionEditDisabledReason(scanner?.user_access_level) ??
                  variantAnalysisRunDisabledReason({
                      running: analysisRunning,
                      lastRunStartedAt: analysisRollup?.latestRun?.started_at ?? null,
                      hasObservations: readout.window.total_observations > 0,
                      now: Date.now(),
                  }),
          }
        : undefined

    return (
        <div className="@container flex flex-col gap-4" data-attr="vision-variants-tab">
            <VariantsExperimentStrip readout={readout} variantColors={variantColors} />
            <VariantDifferencesCard
                readout={readout}
                comparisonState={comparisonState}
                setupDisabledReason={getReplayVisionEditDisabledReason(scanner?.user_access_level)}
                onSetUp={() => {
                    setupAnalysisClicked()
                    openCreateModal('variant-analysis')
                }}
                onOpenScout={existingScout ? () => openScoutSettings(existingScout.skill_name) : undefined}
                runNow={runNow}
            />
            {/* Each watched variant gets a card from the start; the readout lists none only when the
                experiment can't be read, for example after it was deleted. */}
            {readout.variants.length === 0 ? (
                <LemonCard hoverEffect={false} className="p-4 text-sm text-muted">
                    No observations yet. The scanner summarizes sessions of exposed people as they arrive, and each
                    variant shows here once it has some.
                </LemonCard>
            ) : (
                <div
                    className={clsx(
                        'grid grid-cols-1 gap-4 @3xl:grid-cols-2',
                        // A third column only when there is a third variant, so two variants share the width.
                        readout.variants.length > 2 && '@6xl:grid-cols-3'
                    )}
                >
                    {readout.variants.map((variant) => (
                        <VariantCard
                            key={variant.key}
                            variant={variant}
                            color={variantColors[variant.key]}
                            balanced={balanced}
                            themesHint={themesHint}
                            observationsUrl={variantObservationsUrl(scannerId, variant.key)}
                            onOpenObservations={() => variantObservationsOpened(variant.key)}
                        />
                    ))}
                </div>
            )}
            {readout.unattributed_count > 0 && (
                <LemonCard hoverEffect={false} className="p-3 flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 flex-1 text-sm text-muted">
                        <span className="font-semibold text-default">
                            {pluralize(readout.unattributed_count, 'observation')}
                        </span>{' '}
                        <span>{readout.unattributed_count === 1 ? 'has no variant.' : 'have no variant.'}</span>{' '}
                        <span>
                            The person was exposed in an earlier session, or has no recorded flag value, so these stay
                            out of the per-variant counts.
                        </span>
                    </span>
                    <Link
                        to={variantObservationsUrl(scannerId, UNATTRIBUTED_VARIANT)}
                        onClick={() => variantObservationsOpened(UNATTRIBUTED_VARIANT)}
                        className="text-sm"
                        data-attr="vision-variants-view-unattributed"
                    >
                        View them
                    </Link>
                </LemonCard>
            )}
            <ScannerScoutFormModal
                key={createTemplateKey ?? settingsSkillName ?? 'closed'}
                scannerId={scannerId}
                scannerName={scannerName}
            />
        </div>
    )
}
