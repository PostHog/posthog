import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { watchPicksLogic } from '../watchPicksLogic'
import { watchPicksStarterLogic } from '../watchPicksStarterLogic'

export function WatchPicksStarterStatus(): JSX.Element | null {
    const picksLogic = useMountedLogic(watchPicksLogic)
    const { picks } = useValues(picksLogic)
    const logic = watchPicksStarterLogic(picksLogic.props)
    const { startedScanner, burstSessionIds, burstCounts, burstDone, burstStalled, scannedAnyway } = useValues(logic)
    const { showScannedAnyway } = useActions(logic)

    if (!startedScanner) {
        return null
    }
    const total = burstSessionIds.length
    const burstPicks = (picks ?? []).filter(
        (pick) =>
            pick.observation.scanner_id === startedScanner.id && burstSessionIds.includes(pick.observation.session_id)
    ).length
    const finished = Math.max(burstCounts.succeeded + burstCounts.failed, burstPicks)
    const hasPicks = (picks?.length ?? 0) > 0

    if (burstDone && !hasPicks) {
        return (
            <div className="flex flex-col gap-1 p-2" data-attr="vision-watch-picks-starter-nothing">
                <LemonBanner type="info">
                    <div className="flex flex-col gap-2">
                        <span className="font-semibold">
                            {total > 0
                                ? `${pluralize(burstCounts.succeeded, 'recording')} scanned, nothing stood out`
                                : `${startedScanner.name} is on`}
                        </span>
                        <span className="text-xs">
                            {burstStalled && burstCounts.pending > 0
                                ? `${pluralize(burstCounts.pending, 'scan')} still running. New recordings are scanned as they finish and picks show up here.`
                                : 'That happens on a quiet day. New recordings are scanned as they finish and picks show up here.'}
                        </span>
                        <div className="flex flex-wrap gap-2">
                            {burstCounts.succeeded > 0 && scannedAnyway === null && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={showScannedAnyway}
                                    data-attr="vision-watch-picks-starter-show-anyway"
                                >
                                    Show them anyway
                                </LemonButton>
                            )}
                            <LemonButton
                                size="xsmall"
                                to={urls.replayVisionNewScanner()}
                                data-attr="vision-watch-picks-starter-another"
                            >
                                Try another scanner
                            </LemonButton>
                        </div>
                    </div>
                </LemonBanner>
            </div>
        )
    }

    if (burstDone) {
        return burstStalled && burstCounts.pending > 0 ? (
            <div
                className="border-b bg-bg-light px-3 py-2 text-xs text-secondary"
                data-attr="vision-watch-picks-starter-stalled"
            >
                {pluralize(burstCounts.pending, 'scan')} still running. They show up here when they finish.
            </div>
        ) : null
    }

    return (
        <div
            className="flex flex-col gap-1 border-b bg-bg-light px-3 py-2 text-xs"
            data-attr="vision-watch-picks-starter-running"
        >
            <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1 font-semibold">
                    <Spinner className="text-sm" />
                    {startedScanner.name} is scanning
                </span>
                <span className="text-secondary">
                    {finished} / {total}
                </span>
            </div>
            <LemonProgress percent={total === 0 ? 100 : (finished / total) * 100} />
            <span className="text-secondary">Results show up here as each scan finishes.</span>
        </div>
    )
}
