import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import * as noirPng from '@posthog/brand/hoggies/png/noir-1'
import { LemonButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount } from '../../utils/credits'
import { SWEEP_INTERVAL_MINUTES } from '../scannerStatus'
import { watchPicksLogic } from '../watchPicksLogic'
import { watchPicksStaleLogic } from '../watchPicksStaleLogic'

const HedgehogNoir = pngHoggie(noirPng)

export function WatchPicksQuietState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const picksLogic = useMountedLogic(watchPicksLogic)
    const logic = watchPicksStaleLogic(picksLogic.props)
    const {
        backfillCandidates,
        backfillScannerId,
        backfillEstimate,
        backfillEstimateLoading,
        backfillTotals,
        busyScannerId,
        lastSweptAt,
    } = useValues(logic)
    const { pickBackfillScanner, loadBackfillEstimate, startBackfill } = useActions(logic)
    const large = size === 'large'
    const editDisabledReason = getReplayVisionEditDisabledReason()

    useEffect(() => {
        if (backfillScannerId && backfillEstimate?.scannerId !== backfillScannerId) {
            loadBackfillEstimate()
        }
    }, [backfillScannerId, backfillEstimate?.scannerId, loadBackfillEstimate])

    const started = backfillScannerId ? backfillTotals[backfillScannerId] : undefined
    const estimateReady = backfillEstimate?.scannerId === backfillScannerId ? backfillEstimate : null

    return (
        <div
            className={cn(
                'flex flex-col items-center gap-2 text-center text-secondary',
                large ? 'rounded border bg-bg-light p-8 text-sm' : 'p-4 text-xs'
            )}
            data-attr="vision-watch-picks-quiet"
        >
            <HedgehogNoir className={large ? 'h-48 w-48' : 'h-24 w-24'} />
            <span className={cn('font-semibold text-default', large ? 'text-lg' : 'text-sm')}>
                Nothing to watch yet
            </span>
            <span className="max-w-lg">
                {pluralize(backfillCandidates.length, 'scanner')} running
                {lastSweptAt && (
                    <>
                        , last sweep <TZLabel time={lastSweptAt} showPopover={false} noStyles />
                    </>
                )}
                . New recordings are checked every {SWEEP_INTERVAL_MINUTES} minutes and picks appear here.
            </span>
            {backfillCandidates.length > 0 && (
                <div className="mt-1 flex w-full max-w-xs flex-col items-stretch gap-2">
                    {started === undefined ? (
                        <>
                            {backfillCandidates.length > 1 && (
                                <LemonSelect
                                    size="small"
                                    fullWidth
                                    value={backfillScannerId}
                                    onChange={(value) => pickBackfillScanner(value)}
                                    options={backfillCandidates.map((scanner) => ({
                                        value: scanner.id,
                                        label: scanner.name,
                                    }))}
                                    data-attr="vision-watch-picks-quiet-scanner"
                                />
                            )}
                            <LemonButton
                                type="primary"
                                size={large ? 'medium' : 'small'}
                                fullWidth
                                center
                                loading={busyScannerId === backfillScannerId}
                                disabledReason={
                                    editDisabledReason ??
                                    (estimateReady && estimateReady.sessions === 0
                                        ? 'No recording in the last 7 days matches this scanner'
                                        : null)
                                }
                                onClick={() => backfillScannerId && startBackfill(backfillScannerId)}
                                data-attr="vision-watch-picks-quiet-backfill"
                            >
                                Scan the last 7 days now
                            </LemonButton>
                            <span className="text-xs">
                                {backfillEstimateLoading || !estimateReady
                                    ? 'Counting matching recordings'
                                    : `${pluralize(estimateReady.sessions, 'recording')}, about ${formatCreditCount(estimateReady.credits)}`}
                            </span>
                        </>
                    ) : started === 0 ? (
                        <span className="text-xs">
                            No recording in the last 7 days matched. New ones are still scanned.
                        </span>
                    ) : (
                        <span className="text-xs">
                            Scanning {pluralize(started, 'recording')}. Results land here as they finish.
                        </span>
                    )}
                </div>
            )}
            <Link to={urls.replayVision()} className="mt-1" data-attr="vision-watch-picks-empty-link">
                Open Replay vision
            </Link>
        </div>
    )
}
