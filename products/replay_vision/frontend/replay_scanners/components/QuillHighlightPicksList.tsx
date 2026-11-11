import { useActions, useMountedLogic, useValues } from 'kea'

import { Button, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { visionDocsUrl } from '../../components/DocsLink'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { QuillHighlightPickRow } from './QuillHighlightPickRow'
import { QuillHighlightPicksEmptyState } from './QuillHighlightPicksEmptyState'
import { QuillHighlightPicksExtraRows } from './QuillHighlightPicksExtraRows'
import { QuillHighlightPicksScanningState } from './QuillHighlightPicksScanningState'
import { QuillHighlightPicksStaleBanner } from './QuillHighlightPicksStaleBanner'
import { QuillHighlightPicksStarterStatus } from './QuillHighlightPicksStarterStatus'

const LIST_TOP_COUNT = 5

export function QuillHighlightPicksList(): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { picks, picksLoading, picksFailed, activeSessionId } = useValues(picksLogic)
    const { loadPicks, docsOpened } = useActions(picksLogic)
    const { startedScanner, burstDone, burstStalled } = useValues(highlightPicksStarterLogic(picksLogic.props))
    const burstActive = startedScanner !== null && (!burstDone || burstStalled)

    return (
        <div
            data-quill
            className="flex h-full w-full min-w-60 flex-col overflow-hidden rounded border border-border bg-background text-foreground contain-inline-size"
            data-attr="vision-highlight-picks-list"
        >
            <div className="min-h-0 flex-1 overflow-y-auto">
                {picks === null && !picksFailed ? (
                    <div className="flex flex-col gap-2 p-2" aria-busy>
                        {[0, 1, 2, 3].map((i) => (
                            <Skeleton key={i} className="h-16 rounded" />
                        ))}
                    </div>
                ) : picksFailed ? (
                    <div
                        className="flex flex-col items-center gap-2 p-4 text-center text-xs text-muted-foreground"
                        data-attr="vision-highlight-picks-failed"
                    >
                        <span className="text-sm font-semibold text-foreground">Couldn't load highlights</span>
                        <span>Something went wrong on our side. Try again in a moment.</span>
                        <Button
                            variant="outline"
                            size="sm"
                            className="mt-1"
                            loading={picksLoading}
                            onClick={loadPicks}
                            data-attr="vision-highlight-picks-retry"
                        >
                            Try again
                        </Button>
                    </div>
                ) : !picks || picks.length === 0 ? (
                    startedScanner && !burstDone ? (
                        <QuillHighlightPicksScanningState size="small" />
                    ) : startedScanner ? (
                        <>
                            <QuillHighlightPicksStarterStatus />
                            <QuillHighlightPicksExtraRows />
                        </>
                    ) : (
                        <QuillHighlightPicksEmptyState size="small" />
                    )
                ) : (
                    <>
                        {burstActive ? <QuillHighlightPicksStarterStatus /> : <QuillHighlightPicksStaleBanner />}
                        <div className="flex flex-col gap-0.5 p-1">
                            {picks.map((item, index) => (
                                <QuillHighlightPickRow
                                    key={item.observation.id}
                                    item={item}
                                    position={index}
                                    rank={index < LIST_TOP_COUNT ? index + 1 : undefined}
                                    isActive={item.observation.session_id === activeSessionId}
                                />
                            ))}
                        </div>
                        <QuillHighlightPicksExtraRows />
                    </>
                )}
            </div>
            {picks && picks.length > 0 && (
                <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-1.5 text-xs text-muted-foreground">
                    <span>Picks from the last 7 days</span>
                    <Button
                        variant="link"
                        size="inline"
                        render={
                            <LinkPrimitive
                                to={`${visionDocsUrl('what-to-watch')}?utm_medium=in-product&utm_campaign=empty-state-docs-link`}
                                target="_blank"
                            />
                        }
                        onClick={docsOpened}
                        data-attr="vision-highlight-picks-how-chosen"
                    >
                        How picks are chosen
                    </Button>
                </div>
            )}
        </div>
    )
}
