import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import * as asleepPng from '@posthog/brand/hoggies/png/asleep'
import { Button, Item, ItemContent, Switch } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { ReplayScannerApi } from '../../generated/api.schemas'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditsMaybeUsd } from '../../utils/credits'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStaleLogic } from '../highlightPicksStaleLogic'
import { stoppedByFreeCredits } from '../scannerCopy'
import { suggestedCreditLimit } from '../suggestedCreditLimit'
import { QuillHighlightPicksStateFrame } from './QuillHighlightPicksStateFrame'

const HedgehogAsleep = pngHoggie(asleepPng)

export function QuillHighlightPicksBlockedState({
    reason,
    size = 'small',
}: {
    reason: 'all-disabled' | 'all-capped' | 'quota-exhausted'
    size?: 'small' | 'large'
}): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const logic = highlightPicksStaleLogic(picksLogic.props)
    const { scanners, quota, busyScannerId } = useValues(logic)
    const { showUsd } = useValues(visionQuotaLogic)
    const { toggleScanner, raiseLimit } = useActions(logic)
    const [raising, setRaising] = useState<string | null>(null)
    const editDisabledReason = getReplayVisionEditDisabledReason()

    if (reason === 'all-disabled') {
        return (
            <QuillHighlightPicksStateFrame
                size={size}
                image={HedgehogAsleep}
                title="None of your scanners are running"
                body="Turn one on and picks appear after the next matching recording."
                dataAttr="vision-highlight-picks-block-disabled"
                footer={
                    <Button
                        variant="link"
                        size="inline"
                        className="mt-1"
                        render={<LinkPrimitive to={urls.replayVision()} />}
                        data-attr="vision-highlight-picks-block-open"
                    >
                        Open Replay vision
                    </Button>
                }
            >
                <div className="flex flex-col divide-y divide-border rounded border border-border bg-background text-left">
                    {scanners.map((scanner: ReplayScannerApi) => (
                        <div key={scanner.id} className="flex items-center justify-between gap-2 px-3 py-2">
                            <div className="min-w-0">
                                <div className="truncate text-xs font-semibold text-foreground">{scanner.name}</div>
                                <div className="text-xs text-muted-foreground">
                                    {scanner.disabled_reason === 'free_credits_used' ? 'Out of free credits' : 'Off'}{' '}
                                    since <TZLabel time={scanner.updated_at} showPopover={false} noStyles />
                                </div>
                            </div>
                            <Switch
                                size="sm"
                                checked={scanner.enabled ?? false}
                                disabled={busyScannerId === scanner.id}
                                disabledReason={editDisabledReason}
                                onCheckedChange={(checked) => toggleScanner(scanner.id, checked)}
                                data-attr="vision-highlight-picks-block-toggle"
                            />
                        </div>
                    ))}
                </div>
            </QuillHighlightPicksStateFrame>
        )
    }

    const capped = reason === 'all-capped' ? scanners.filter((scanner) => scanner.enabled && scanner.limit_reached) : []
    const resetsAt = quota?.period_end
    const freeSampleUsedUp = capped.length > 0 && capped.every((scanner) => stoppedByFreeCredits(scanner))
    return (
        <Item
            data-quill
            variant="outline"
            tone="warning"
            className="m-2"
            data-attr="vision-highlight-picks-block-capped"
        >
            <ItemContent className="gap-2">
                <span className="font-semibold">
                    {reason === 'quota-exhausted'
                        ? 'Scanners paused: your Replay vision credits are used up for this period'
                        : freeSampleUsedUp
                          ? 'Scanners paused: your free sample is used up'
                          : 'Scanners paused: every running scanner reached its credit limit'}
                </span>
                <span className="text-xs">
                    {freeSampleUsedUp ? 'Set a budget to keep scanning, or wait. ' : ''}
                    {resetsAt ? (
                        <>
                            Resets <TZLabel time={resetsAt} showPopover={false} noStyles />. Picks stop until then.
                        </>
                    ) : (
                        'Picks stop until the period resets.'
                    )}
                </span>
                {capped.map((scanner) => {
                    const next = suggestedCreditLimit(scanner)
                    const freeOnly = stoppedByFreeCredits(scanner)
                    return (
                        <div key={scanner.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                            <span className="font-semibold">{scanner.name}</span>
                            {raising === scanner.id ? (
                                <span className="flex items-center gap-1">
                                    <Button
                                        variant="primary"
                                        size="xs"
                                        loading={busyScannerId === scanner.id}
                                        onClick={() => {
                                            raiseLimit(scanner.id, next)
                                            setRaising(null)
                                        }}
                                        data-attr="vision-highlight-picks-block-raise-confirm"
                                    >
                                        Set {formatCreditsMaybeUsd(next, showUsd)} a month
                                    </Button>
                                    <Button
                                        size="xs"
                                        onClick={() => setRaising(null)}
                                        data-attr="vision-highlight-picks-block-raise-cancel"
                                    >
                                        Cancel
                                    </Button>
                                </span>
                            ) : (
                                <Button
                                    variant="outline"
                                    size="xs"
                                    disabledReason={editDisabledReason}
                                    onClick={() => setRaising(scanner.id)}
                                    data-attr="vision-highlight-picks-block-raise"
                                >
                                    {freeOnly ? 'Set a budget' : 'Raise limit'}
                                </Button>
                            )}
                        </div>
                    )
                })}
                <Button
                    variant="link"
                    size="inline"
                    className="self-start text-xs"
                    render={<LinkPrimitive to={`${urls.replayVision()}?tab=usage`} />}
                    data-attr="vision-highlight-picks-block-usage"
                >
                    See usage
                </Button>
            </ItemContent>
        </Item>
    )
}
