import { useActions, useMountedLogic, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount, formatCreditNumber, formatCreditsMaybeUsd } from '../../utils/credits'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { BUDGET_PRESETS, QUICKSTART_SCANNER, TARGET_MONTHLY_SCANS, weeklyVolume } from '../highlightPicksStarter'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { highlightPicksVolumeLogic } from '../highlightPicksVolumeLogic'
import { HighlightPicksStateFrame } from './HighlightPicksStateFrame'

const SCANS_PER_DAY = Math.round(TARGET_MONTHLY_SCANS / 30)
const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

function hoursLabel(hours: number): string {
    return hours < 1 ? `${Math.max(1, Math.round(hours * 60))}m` : `${Math.round(hours)}h`
}

export function HighlightPicksStarter({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { props: picksProps } = useMountedLogic(highlightPicksLogic)
    const logic = highlightPicksStarterLogic(picksProps)
    const { burstPlan, spendMode, freeAvailable, budget, starting, startError, freeCreditsLeft, candidateRecordings } =
        useValues(logic)
    const { setBudget, chooseBudget, startScanner } = useActions(logic)
    const { volumeEstimate, volumeEstimateLoading } = useValues(highlightPicksVolumeLogic)
    const { showUsd } = useValues(visionQuotaLogic)
    const large = size === 'large'
    const editDisabledReason = getReplayVisionEditDisabledReason()

    const volume = weeklyVolume(volumeEstimate, candidateRecordings)
    const burstCount = burstPlan.sessionIds.length
    const costLine =
        spendMode === 'free'
            ? `Free credits only${freeCreditsLeft !== null ? `, ${formatCreditCount(freeCreditsLeft)} left` : ''}. Stops by itself at the limit.`
            : freeAvailable
              ? 'A monthly budget you set. Free credits are used first.'
              : 'Free credits are used up, so this scanner needs a monthly limit.'
    const tiles: [string, string, string, boolean][] | null = volume
        ? [
              ['Recorded', String(volume.recorded), 'this week', false],
              ['To watch', volume.hours === null ? '-' : hoursLabel(volume.hours), 'at normal speed', false],
              ['Worth watching', `~${volume.picks}`, 'typical at this volume', true],
          ]
        : null

    return (
        <HighlightPicksStateFrame
            size={size}
            image={HedgehogMagnifyingGlass}
            title={volume ? 'Your week in recordings' : 'Nothing to watch yet'}
            body={
                volume
                    ? null
                    : `Start ${QUICKSTART_SCANNER.name}, a scanner that reads each new recording and surfaces the ones worth watching.`
            }
            dataAttr="vision-highlight-picks-starter"
            footer={
                <div className="mt-1 flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
                    {freeAvailable && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            disabledReason={starting ? 'Starting' : null}
                            onClick={() => chooseBudget(spendMode === 'free')}
                            data-attr="vision-highlight-picks-starter-toggle-budget"
                        >
                            {spendMode === 'free' ? 'Set a monthly budget instead' : 'Use free credits instead'}
                        </LemonButton>
                    )}
                    <Link to={urls.replayVisionNewScanner()} data-attr="vision-highlight-picks-starter-own-goal">
                        Write my own goal
                    </Link>
                </div>
            }
        >
            {volumeEstimateLoading && !volume ? (
                <LemonSkeleton className="h-16 w-full rounded" />
            ) : tiles ? (
                <>
                    <div className="grid grid-cols-3 gap-1.5" data-attr="vision-highlight-picks-starter-volume">
                        {tiles.map(([label, value, caption, accent]) => (
                            <div
                                key={label}
                                className="flex flex-col items-center gap-0.5 rounded border bg-bg-light px-1 py-2 text-center"
                            >
                                <span className="text-xxs font-bold uppercase tracking-wide text-secondary">
                                    {label}
                                </span>
                                <span className={cn('text-xl font-bold leading-tight', accent && 'text-accent')}>
                                    {value}
                                </span>
                                <span className="text-xxs text-secondary">{caption}</span>
                            </div>
                        ))}
                    </div>
                    <span className="text-xs text-secondary">
                        A scanner reads all {volume?.recorded} in minutes and hands you the few worth opening.
                    </span>
                </>
            ) : null}
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
                        ? `Scan the newest ${burstCount}, free`
                        : 'Start free scanner'
                    : `Start with ${formatCreditCount(budget)} a month`}
            </LemonButton>
            <span className="text-xxs text-secondary">
                Then every new recording, about {SCANS_PER_DAY} a day. {costLine}
            </span>
        </HighlightPicksStateFrame>
    )
}
