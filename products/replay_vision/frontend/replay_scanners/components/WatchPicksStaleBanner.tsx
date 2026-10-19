import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { scannerEditUrl } from '../scannerEditorSceneLogic'
import { watchPicksLogic } from '../watchPicksLogic'
import { watchPicksStaleLogic } from '../watchPicksStaleLogic'
import { WatchPicksBlockedState } from './WatchPicksBlockedState'

export function WatchPicksStaleBanner(): JSX.Element | null {
    const picksLogic = useMountedLogic(watchPicksLogic)
    const logic = watchPicksStaleLogic(picksLogic.props)
    const { picks } = useValues(picksLogic)
    const {
        staleReason,
        droughtScanners,
        scanners,
        busyScannerId,
        backfillTotals,
        quietWeek,
        nextBest,
        nextBestLoading,
    } = useValues(logic)
    const { startBackfill, loadNextBest } = useActions(logic)
    const editDisabledReason = getReplayVisionEditDisabledReason()

    if (!staleReason) {
        return null
    }
    if (staleReason === 'all-disabled' || staleReason === 'all-capped' || staleReason === 'quota-exhausted') {
        return <WatchPicksBlockedState reason={staleReason} />
    }

    const newest = (picks ?? []).reduce<string | null>(
        (latest, pick) => (!latest || pick.observation.created_at > latest ? pick.observation.created_at : latest),
        null
    )
    const running = scanners.filter((scanner) => scanner.enabled && !scanner.limit_reached).length

    if (staleReason === 'drought') {
        return (
            <LemonBanner type="warning" className="m-2" data-attr="vision-watch-picks-stale-drought">
                <div className="flex flex-col gap-2 text-xs">
                    {droughtScanners.map((scanner) => {
                        const total = backfillTotals[scanner.id]
                        return (
                            <div key={scanner.id} className="flex flex-col gap-1">
                                <span className="font-semibold">
                                    {scanner.name} has not matched anything since you changed it
                                </span>
                                {total === undefined ? (
                                    <div className="flex flex-wrap gap-2">
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            loading={busyScannerId === scanner.id}
                                            disabledReason={editDisabledReason}
                                            onClick={() => startBackfill(scanner.id)}
                                            data-attr="vision-watch-picks-stale-backfill"
                                        >
                                            Scan the last 7 days now
                                        </LemonButton>
                                        <Link
                                            to={scannerEditUrl(scanner.id, null)}
                                            data-attr="vision-watch-picks-stale-review"
                                        >
                                            Review filters
                                        </Link>
                                    </div>
                                ) : total === 0 ? (
                                    <span>
                                        No recording in the last 7 days passes its filters.{' '}
                                        <Link
                                            to={scannerEditUrl(scanner.id, null)}
                                            data-attr="vision-watch-picks-stale-review"
                                        >
                                            Review filters
                                        </Link>
                                    </span>
                                ) : (
                                    <span>
                                        Scanning {pluralize(total, 'recording')}. Results land here as they finish.
                                    </span>
                                )}
                            </div>
                        )
                    })}
                </div>
            </LemonBanner>
        )
    }

    if (staleReason === 'caught-up') {
        return (
            <div
                className="border-b bg-bg-light px-3 py-2 text-xs text-secondary"
                data-attr="vision-watch-picks-stale-caught-up"
            >
                <span className="font-semibold text-default">You are caught up.</span>{' '}
                {newest && (
                    <>
                        Last pick <TZLabel time={newest} showPopover={false} noStyles />.{' '}
                    </>
                )}
                {pluralize(running, 'scanner')} running. New picks appear here without a refresh.
            </div>
        )
    }

    return (
        <div
            className="flex flex-col gap-1 border-b bg-bg-light px-3 py-2 text-xs"
            data-attr="vision-watch-picks-stale-quiet"
        >
            <span className="font-semibold">Quiet week</span>
            {quietWeek ? (
                <span className="text-secondary">
                    {pluralize(quietWeek.scanned, 'recording')} scanned, {quietWeek.succeeded} finished, none stood out
                    enough to be a pick.
                </span>
            ) : (
                <span className="text-secondary">
                    Nothing new{newest ? ' since ' : ''}
                    {newest && <TZLabel time={newest} showPopover={false} noStyles />}. {pluralize(running, 'scanner')}{' '}
                    running.
                </span>
            )}
            {nextBest === null ? (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    className="self-start"
                    loading={nextBestLoading}
                    onClick={loadNextBest}
                    data-attr="vision-watch-picks-stale-next-best"
                >
                    Show the newest results anyway
                </LemonButton>
            ) : null}
        </div>
    )
}
