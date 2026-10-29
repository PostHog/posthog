import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { HighlightPickRow } from './HighlightPickRow'
import { HighlightPicksEmptyState } from './HighlightPicksEmptyState'
import { HighlightPicksExtraRows } from './HighlightPicksExtraRows'
import { HighlightPicksStaleBanner } from './HighlightPicksStaleBanner'
import { HighlightPicksStarterStatus } from './HighlightPicksStarterStatus'

const LIST_TOP_COUNT = 5

export function HighlightPicksList(): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { picks, picksLoad, picksLoading, picksFailed, activeSessionId } = useValues(picksLogic)
    const { loadPicks } = useActions(picksLogic)
    const { startedScanner, burstDone, burstStalled } = useValues(highlightPicksStarterLogic(picksLogic.props))
    const burstActive = startedScanner !== null && (!burstDone || burstStalled)

    return (
        <div
            className="flex h-full w-full min-w-60 flex-col overflow-hidden rounded border bg-bg-light contain-inline-size"
            data-attr="vision-highlight-picks-list"
        >
            <div className="min-h-0 flex-1 overflow-y-auto">
                {picks === null && !picksFailed ? (
                    <div className="flex flex-col gap-2 p-2" aria-busy>
                        {[0, 1, 2, 3].map((i) => (
                            <LemonSkeleton key={i} className="h-16 rounded" />
                        ))}
                    </div>
                ) : picksFailed ? (
                    <div
                        className="flex flex-col items-center gap-2 p-4 text-center text-xs text-secondary"
                        data-attr="vision-highlight-picks-failed"
                    >
                        <span className="text-sm font-semibold text-default">Couldn't load highlights</span>
                        <span>Something went wrong on our side. Try again in a moment.</span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            className="mt-1"
                            loading={picksLoading}
                            onClick={loadPicks}
                            data-attr="vision-highlight-picks-retry"
                        >
                            Try again
                        </LemonButton>
                    </div>
                ) : !picks || picks.length === 0 ? (
                    startedScanner ? (
                        <>
                            <HighlightPicksStarterStatus />
                            <HighlightPicksExtraRows />
                        </>
                    ) : (
                        <HighlightPicksEmptyState size="small" />
                    )
                ) : (
                    <>
                        {burstActive ? <HighlightPicksStarterStatus /> : <HighlightPicksStaleBanner />}
                        <div className="flex flex-col gap-0.5 p-1">
                            {picks.map((item, index) => (
                                <HighlightPickRow
                                    key={`${picksLoad?.feedLoadId}-${item.observation.id}`}
                                    item={item}
                                    position={index}
                                    rank={index < LIST_TOP_COUNT ? index + 1 : undefined}
                                    isActive={item.observation.session_id === activeSessionId}
                                />
                            ))}
                        </div>
                        <HighlightPicksExtraRows />
                    </>
                )}
            </div>
        </div>
    )
}
