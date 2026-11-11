import { useActions, useMountedLogic, useValues } from 'kea'

import { Button, Item, ItemContent, Progress, Spinner } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'

export function QuillHighlightPicksStarterStatus(): JSX.Element | null {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { picks } = useValues(picksLogic)
    const logic = highlightPicksStarterLogic(picksLogic.props)
    const { startedScanner, burstSessionIds, burstCounts, burstDone, burstStalled, scannedAnyway, feedWindowOpen } =
        useValues(logic)
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
            <div data-quill className="flex flex-col gap-1 p-2" data-attr="vision-highlight-picks-starter-nothing">
                <Item variant="outline" tone="info">
                    <ItemContent className="gap-2">
                        <span className="font-semibold">
                            {total === 0
                                ? 'Your scanner is on'
                                : feedWindowOpen
                                  ? `${pluralize(burstCounts.succeeded, 'recording')} scanned`
                                  : `${pluralize(burstCounts.succeeded, 'recording')} scanned, nothing stood out`}
                        </span>
                        <span className="text-xs">
                            {burstStalled && burstCounts.pending > 0
                                ? `${pluralize(burstCounts.pending, 'scan')} still running. New recordings are scanned as they finish and picks show up here.`
                                : feedWindowOpen
                                  ? 'Highlights show up here a few minutes after scans finish.'
                                  : 'That happens on a quiet day. New recordings are scanned as they finish and picks show up here.'}
                        </span>
                        <div className="flex flex-wrap gap-2">
                            {burstCounts.succeeded > 0 && scannedAnyway === null && (
                                <Button
                                    variant="outline"
                                    size="xs"
                                    onClick={showScannedAnyway}
                                    data-attr="vision-highlight-picks-starter-show-anyway"
                                >
                                    Show them anyway
                                </Button>
                            )}
                            <Button
                                size="xs"
                                render={<LinkPrimitive to={urls.replayVisionNewScanner()} />}
                                data-attr="vision-highlight-picks-starter-another"
                            >
                                Try another scanner
                            </Button>
                        </div>
                    </ItemContent>
                </Item>
            </div>
        )
    }

    if (burstDone) {
        return burstStalled && burstCounts.pending > 0 ? (
            <div
                data-quill
                className="border-b border-border px-3 py-2 text-xs text-muted-foreground"
                data-attr="vision-highlight-picks-starter-stalled"
            >
                {pluralize(burstCounts.pending, 'scan')} still running. They show up here when they finish.
            </div>
        ) : null
    }

    return (
        <div
            data-quill
            className="flex flex-col gap-1 border-b border-border px-3 py-2 text-xs text-foreground"
            data-attr="vision-highlight-picks-starter-running"
        >
            <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1 font-semibold">
                    <Spinner className="size-3.5" />
                    Scanning sessions
                </span>
                <span className="text-muted-foreground">
                    {finished} / {total}
                </span>
            </div>
            <Progress value={total === 0 ? 100 : (finished / total) * 100} />
            <span className="text-muted-foreground">Highlights show up here a few minutes after scans finish.</span>
        </div>
    )
}
