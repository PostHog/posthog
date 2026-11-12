import { useActions, useMountedLogic, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { Button, Item, ItemContent, ItemDescription, Skeleton, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount, formatCreditNumber, formatCreditsMaybeUsd } from '../../utils/credits'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { BUDGET_PRESETS, TARGET_MONTHLY_SCANS, weeklyVolume } from '../highlightPicksStarter'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { highlightPicksVolumeLogic } from '../highlightPicksVolumeLogic'
import { QuillHighlightPicksStateFrame } from './QuillHighlightPicksStateFrame'
import { QuillHighlightPicksVolumeTiles } from './QuillHighlightPicksVolumeTiles'

const SCANS_PER_DAY = Math.round(TARGET_MONTHLY_SCANS / 30)
const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function QuillHighlightPicksStarter({ size }: { size: 'small' | 'large' }): JSX.Element {
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
            ? `Free credits only${freeCreditsLeft !== null ? `, ${formatCreditCount(freeCreditsLeft)} left` : ''}. Stops when they run out.`
            : freeAvailable
              ? 'A monthly budget you set. Free credits are used first.'
              : 'Free credits are used up, so this scanner needs a monthly limit.'

    return (
        <QuillHighlightPicksStateFrame
            size={size}
            image={HedgehogMagnifyingGlass}
            title={
                loading ? (
                    <Skeleton className="h-5 w-48" />
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
                        <Button
                            size="xs"
                            disabledReason={starting ? 'Starting' : undefined}
                            onClick={() => {
                                emptyStateAction('no-scanners', spendMode === 'free' ? 'set_budget' : 'use_free')
                                chooseBudget(spendMode === 'free')
                            }}
                            data-attr="vision-highlight-picks-starter-toggle-budget"
                        >
                            {spendMode === 'free' ? 'Set a monthly budget instead' : 'Use free credits instead'}
                        </Button>
                    )}
                    <Button
                        variant="link"
                        size="inline"
                        render={<LinkPrimitive to={urls.replayVisionNewScanner()} />}
                        onClick={() => emptyStateAction('no-scanners', 'own_goal')}
                        data-attr="vision-highlight-picks-starter-own-goal"
                    >
                        Write my own goal
                    </Button>
                </div>
            }
        >
            <QuillHighlightPicksVolumeTiles
                volume={volume}
                loading={loading}
                dataAttr="vision-highlight-picks-starter-volume"
            />
            {volume && (
                <span className="text-xs text-muted-foreground">
                    {burstCount > 0
                        ? `A scanner reads the newest ${burstCount} now and hands you the few worth opening.`
                        : 'A scanner reads new recordings and hands you the few worth opening.'}
                </span>
            )}
            {spendMode === 'budget' && (
                <>
                    <ToggleGroup
                        variant="outline"
                        size="sm"
                        className="w-full"
                        value={[String(budget)]}
                        onValueChange={(value: string[]) => value[0] && setBudget(Number(value[0]))}
                    >
                        {BUDGET_PRESETS.map((preset) => (
                            <ToggleGroupItem
                                key={preset}
                                value={String(preset)}
                                className="flex-1"
                                data-attr="vision-highlight-picks-starter-budget"
                            >
                                {formatCreditNumber(preset)}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                    <span className="text-xs">{formatCreditsMaybeUsd(budget, showUsd)} a month</span>
                </>
            )}
            {startError && (
                <Item variant="outline" tone="destructive">
                    <ItemContent>
                        <ItemDescription>{startError}</ItemDescription>
                    </ItemContent>
                </Item>
            )}
            <Button
                variant="primary"
                size={large ? 'default' : 'sm'}
                className="w-full"
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
            </Button>
            <span className="text-xxs text-muted-foreground">
                Then about {SCANS_PER_DAY} new recordings a day. {costLine}
            </span>
        </QuillHighlightPicksStateFrame>
    )
}
