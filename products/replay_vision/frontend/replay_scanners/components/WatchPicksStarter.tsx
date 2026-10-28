import { useActions, useMountedLogic, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonBanner, LemonButton, LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount, formatCreditNumber, formatCreditsMaybeUsd } from '../../utils/credits'
import { watchPicksLogic } from '../watchPicksLogic'
import { BUDGET_PRESETS, QUICKSTART_SCANNER, TARGET_MONTHLY_SCANS } from '../watchPicksStarter'
import { watchPicksStarterLogic } from '../watchPicksStarterLogic'
import { WatchPicksStateFrame } from './WatchPicksStateFrame'

const SCANS_PER_DAY = Math.round(TARGET_MONTHLY_SCANS / 30)
const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function WatchPicksStarter({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { props: picksProps } = useMountedLogic(watchPicksLogic)
    const logic = watchPicksStarterLogic(picksProps)
    const { burstPlan, spendMode, freeAvailable, budget, starting, startError, freeCreditsLeft } = useValues(logic)
    const { setBudget, chooseBudget, startScanner } = useActions(logic)
    const { showUsd } = useValues(visionQuotaLogic)
    const large = size === 'large'
    const editDisabledReason = getReplayVisionEditDisabledReason()

    const burstCount = burstPlan.sessionIds.length
    const rows: [string, string][] = [
        [
            'Scans now',
            burstCount > 0 ? pluralize(burstCount, 'recent recording') : 'nothing yet, no eligible recordings loaded',
        ],
        ['Then', `new recordings, about ${SCANS_PER_DAY} a day`],
        [
            'Cost',
            spendMode === 'free'
                ? `free credits only${freeCreditsLeft !== null ? `, ${formatCreditCount(freeCreditsLeft)} left` : ''}. Stops by itself at the limit.`
                : freeAvailable
                  ? 'a monthly budget you set. Free credits are used first.'
                  : 'free credits are used up, so this scanner needs a monthly limit',
        ],
    ]
    return (
        <WatchPicksStateFrame
            size={size}
            image={HedgehogMagnifyingGlass}
            title="Nothing to watch yet"
            body={`Start ${QUICKSTART_SCANNER.name}, a scanner that reads each new recording and surfaces the ones worth watching.`}
            dataAttr="vision-watch-picks-starter"
            footer={
                <Link
                    to={urls.replayVisionNewScanner()}
                    className="mt-1"
                    data-attr="vision-watch-picks-starter-own-goal"
                >
                    Write my own goal
                </Link>
            }
        >
            <div className="flex flex-col divide-y rounded border bg-bg-light text-left">
                {rows.map(([label, value]) => (
                    <div key={label} className="flex flex-col gap-0.5 px-3 py-2">
                        <span className="text-xs font-semibold text-default">{label}</span>
                        <span className="text-xs text-secondary">{value}</span>
                    </div>
                ))}
            </div>
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
                            'data-attr': 'vision-watch-picks-starter-budget',
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
                data-attr="vision-watch-picks-starter-start"
            >
                {spendMode === 'free' ? 'Start free scanner' : `Start with ${formatCreditCount(budget)} a month`}
            </LemonButton>
            {freeAvailable && (
                <LemonButton
                    type="tertiary"
                    size={large ? 'medium' : 'small'}
                    fullWidth
                    center
                    disabledReason={starting ? 'Starting' : null}
                    onClick={() => chooseBudget(spendMode === 'free')}
                    data-attr="vision-watch-picks-starter-toggle-budget"
                >
                    {spendMode === 'free' ? 'Set a monthly budget instead' : 'Use free credits instead'}
                </LemonButton>
            )}
        </WatchPicksStateFrame>
    )
}
