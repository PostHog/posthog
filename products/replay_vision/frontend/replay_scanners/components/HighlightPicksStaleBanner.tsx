import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { ReactNode } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStaleLogic } from '../highlightPicksStaleLogic'
import { scannerEditUrl } from '../scannerEditorSceneLogic'
import { markScannerGoalDraftIntent } from '../scannerHandoffIntent'
import { HighlightPicksBlockedState } from './HighlightPicksBlockedState'
import { SCANNER_GOAL_STARTERS } from './scannerGoalStarters'

const QUIET_WEEK_GOAL_KEYS = ['dead_end', 'frustration_score']
const quietWeekGoals = SCANNER_GOAL_STARTERS.filter((starter) => QUIET_WEEK_GOAL_KEYS.includes(starter.key))

export function HighlightPicksStaleBanner(): JSX.Element | null {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const logic = highlightPicksStaleLogic(picksLogic.props)
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
    const { startBackfill, loadNextBest, pickSharperGoal } = useActions(logic)
    const editDisabledReason = getReplayVisionEditDisabledReason()

    if (!staleReason) {
        return null
    }
    if (staleReason === 'all-disabled' || staleReason === 'all-capped' || staleReason === 'quota-exhausted') {
        return <HighlightPicksBlockedState reason={staleReason} />
    }

    const newest = (picks ?? []).reduce<string | null>(
        (latest, pick) => (!latest || pick.observation.created_at > latest ? pick.observation.created_at : latest),
        null
    )
    const runningScanners = scanners.filter((scanner) => scanner.enabled && !scanner.limit_reached)
    const running = runningScanners.length

    if (staleReason === 'drought') {
        return (
            <LemonBanner type="warning" className="m-2" data-attr="vision-highlight-picks-stale-drought">
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
                                            data-attr="vision-highlight-picks-stale-backfill"
                                        >
                                            Scan the last 7 days now
                                        </LemonButton>
                                        <Link
                                            to={scannerEditUrl(scanner.id, null)}
                                            data-attr="vision-highlight-picks-stale-review"
                                        >
                                            Review filters
                                        </Link>
                                    </div>
                                ) : total === 0 ? (
                                    <span>
                                        No recording in the last 7 days passes its filters.{' '}
                                        <Link
                                            to={scannerEditUrl(scanner.id, null)}
                                            data-attr="vision-highlight-picks-stale-review"
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
                data-attr="vision-highlight-picks-stale-caught-up"
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

    const stats: [string, ReactNode][] = [
        ['Scanned', quietWeek ? String(quietWeek.scanned) : null],
        ['Picks', String((picks ?? []).length)],
        ['Last pick', newest ? <TZLabel key="last-pick" time={newest} showPopover={false} noStyles /> : null],
    ]
    return (
        <div
            className="flex flex-col gap-2 border-b bg-bg-light px-3 py-2 text-xs"
            data-attr="vision-highlight-picks-stale-quiet"
        >
            <div className="flex items-baseline justify-between gap-2">
                <span className="font-semibold">Quiet week</span>
                {runningScanners.length === 1 && (
                    <span className="truncate text-secondary">{runningScanners[0].name}</span>
                )}
            </div>
            <div className="flex gap-4">
                {stats.map(([label, value]) => (
                    <div key={label} className="flex flex-col">
                        <span className="text-xxs font-bold uppercase tracking-wide text-secondary">{label}</span>
                        {value ? (
                            <span className="text-base font-bold leading-tight">{value}</span>
                        ) : (
                            <LemonSkeleton className="h-5 w-8" />
                        )}
                    </div>
                ))}
            </div>
            <span className="text-secondary">Nothing stood out this week. Try a sharper goal.</span>
            {quietWeekGoals.map((starter) => (
                <LemonButton
                    key={starter.key}
                    type="secondary"
                    size="small"
                    fullWidth
                    icon={starter.icon}
                    disabledReason={editDisabledReason}
                    to={combineUrl(urls.replayVisionNewScanner(), { goal: starter.goal }).url}
                    onClick={() => {
                        markScannerGoalDraftIntent({ goal: starter.goal })
                        pickSharperGoal(starter.key)
                    }}
                    data-attr={`vision-highlight-picks-stale-goal-${starter.key}`}
                >
                    <span className="flex min-w-0 flex-col text-left">
                        <span>{starter.question}</span>
                        <span className="truncate text-xxs font-normal text-secondary">{starter.goal}</span>
                    </span>
                </LemonButton>
            ))}
            {nextBest === null ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-start"
                    loading={nextBestLoading}
                    onClick={loadNextBest}
                    data-attr="vision-highlight-picks-stale-next-best"
                >
                    Show the newest results anyway
                </LemonButton>
            ) : null}
        </div>
    )
}
