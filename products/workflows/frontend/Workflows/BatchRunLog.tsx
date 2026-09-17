import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { tagTypeForLevel } from 'scenes/hog-functions/logs/LogsViewer'
import { logsViewerLogic } from 'scenes/hog-functions/logs/logsViewerLogic'

/**
 * What a batch run recorded about itself: an audience cut at the batch limit, a cancel, a resolver
 * failure. These entries carry the batch job id as their instance, so they never appear in a
 * person's row below. There are at most a few of them, so this is a list, not a log viewer, and
 * it renders nothing at all for the common run that recorded nothing.
 */
export function BatchRunLog({ jobId, createdAt }: { jobId: string; createdAt: string }): JSX.Element | null {
    // The viewer looks back seven days unless told otherwise, while these entries are kept for
    // ninety. Without an anchor on the run's own date, every run older than a week reads as
    // having recorded nothing.
    const dateFrom = dayjs(createdAt).subtract(1, 'day').format('YYYY-MM-DD')

    const { unGroupedLogs } = useValues(
        logsViewerLogic({
            logicKey: `batch-run-log-${jobId}`,
            sourceType: 'hog_flow',
            sourceId: jobId,
            groupByInstanceId: false,
            disableUrlSync: true,
            defaultFilters: { instanceId: jobId, dateFrom },
        })
    )

    if (unGroupedLogs.length === 0) {
        return null
    }

    // The fetch is newest-first to match the viewer; the run reads in execution order.
    const entries = [...unGroupedLogs].reverse()

    return (
        <div className="flex flex-col gap-2">
            <span className="text-muted">Run log</span>
            <div className="border rounded bg-surface-primary divide-y" data-attr="batch-run-log">
                {entries.map((entry, index) => (
                    <div key={`${entry.rawTimestamp}-${index}`} className="flex items-start gap-3 px-3 py-2">
                        <span className="text-secondary whitespace-nowrap">
                            <TZLabel time={entry.timestamp} />
                        </span>
                        <LemonTag type={tagTypeForLevel(entry.level)}>{entry.level.toUpperCase()}</LemonTag>
                        <code className="whitespace-pre-wrap">{entry.message}</code>
                    </div>
                ))}
            </div>
        </div>
    )
}
