import { useActions, useMountedLogic, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount, formatCreditNumber, formatCreditsMaybeUsd } from '../../utils/credits'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { BUDGET_PRESETS, TARGET_MONTHLY_SCANS, weeklyVolume } from '../highlightPicksStarter'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { highlightPicksVolumeLogic } from '../highlightPicksVolumeLogic'
import { HighlightPicksStateFrame } from './HighlightPicksStateFrame'
import { HighlightPicksVolumeTiles } from './HighlightPicksVolumeTiles'

const SCANS_PER_DAY = Math.round(TARGET_MONTHLY_SCANS / 30)
const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function HighlightPicksStarter({ size }: { size: 'small' | 'large' }): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { emptyStateAction } = useActions(picksLogic)
    const logic = highlightPicksStarterLogic(picksLogic.props)
    const { burstPlan, spendMode, freeAvailable, budget, starting, startError, freeCreditsLeft, candidateRecordings } =
        useValues(logic)
    const { setBudget, chooseBudget, startScanner } = useActions(logic)
    const { volumeEstimate, volumeEstimateLoading } = useValues(highlightPicksVolumeLogic)
    const { showUsd } = useValues(visionQuotaLogic)
    const large = size === 'large'
    const editDisabledReason = getReplayVisionEditDisabledReason()

    const volume = weeklyVolume(volumeEstimate, candidateRecordings)
    const loading = volumeEstimateLoading && !volume
    const burstCount = burstPlan.sessionIds.length
    const costLine =
        spendMode === 'free'
            ? `Free credits only${freeCreditsLeft !== null ? `, ${formatCreditCount(freeCreditsLeft)} left` : ''}. Stops by itself at the limit.`
            : freeAvailable
              ? 'A monthly budget you set. Free credits are used first.'
              : 'Free credits are used up, so this scanner needs a monthly limit.'

    return (
        <HighlightPicksStateFrame
            size={size}
            image={HedgehogMagnifyingGlass}
            title={
                loading ? (
                    <LemonSkeleton className="h-5 w-48" />
                ) : volume ? (
                    'Your week in recordings'
                ) : (
                    'Nothing to watch yet'
                )
            }
            body={
                volume || loading
                    ? null
                    : 'Start scanning your sessions. A scanner reads new recordings and surfaces the ones worth watching.'
            }
            dataAttr="vision-highlight-picks-starter"
            footer={
                <div className="mt-1 flex flex-wrap items-baseline justify-center gap-x-3 gap-y-1">
                    {freeAvailable && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            disabledReason={starting ? 'Starting' : null}
                            onClick={() => {
                                emptyStateAction('no-scanners', spendMode === 'free' ? 'set_budget' : 'use_free')
                                chooseBudget(spendMode === 'free')
                            }}
                            data-attr="vision-highlight-picks-starter-toggle-budget"
                        >
                            {spendMode === 'free' ? 'Set a monthly budget instead' : 'Use free credits instead'}
                        </LemonButton>
                    )}
                    <Link
                        to={urls.replayVisionNewScanner()}
                        onClick={() => emptyStateAction('no-scanners', 'own_goal')}
                        data-attr="vision-highlight-picks-starter-own-goal"
                    >
                        Write my own goal
                    </Link>
                </div>
            }
        >
            <HighlightPicksVolumeTiles
                volume={volume}
                loading={loading}
                dataAttr="vision-highlight-picks-starter-volume"
            />
            {volume && (
                <span className="text-xs text-secondary">
                    {burstCount > 0
                        ? `A scanner reads the newest ${burstCount} now and hands you the few worth opening.`
                        : 'A scanner reads new recordings and hands you the few worth opening.'}
                </span>
            )}
            {spendMode === 'budget' && (
                <>
                    <LemonSegmentedButton
                        size="small"
                        fullWidth
                        value={budget}
                        onChange={(value) => setBudget(value)}
                        options={BUDGET_PRESETS.map((preset) => ({
                            value: preset,
                            label: formatCreditNumber(preset),
                            'data-attr': 'vision-highlight-picks-starter-budget',
                        }))}
                    />
                    <span className="text-xs">{formatCreditsMaybeUsd(budget, showUsd)} a month</span>
                </>
            )}
            {startError && <LemonBanner type="error">{startError}</LemonBanner>}
            <LemonButton
                type="primary"
                size={large ? 'medium' : 'small'}
                fullWidth
                center
                loading={starting}
                disabledReason={editDisabledReason}
                onClick={startScanner}
                data-attr="vision-highlight-picks-starter-start"
            >
                {spendMode === 'free'
                    ? burstCount > 0
                        ? `Scan ${pluralize(burstCount, 'recent recording')} for free`
                        : 'Start free scanner'
                    : `Start with ${formatCreditCount(budget)} a month`}
            </LemonButton>
            <span className="text-xxs text-secondary">
                Then about {SCANS_PER_DAY} new recordings a day. {costLine}
            </span>
        </HighlightPicksStateFrame>
    )
}
