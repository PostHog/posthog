import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { workflowId } from '../../lib/ciExplorerGraph'
import { buildPushTimeline } from '../../lib/ciTimeline'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CITimeline } from '../CITimeline'

export function CIExplorerTimeline(): JSX.Element {
    const {
        repoOwner,
        repoName,
        activePush,
        workflowRuns,
        jobsByRun,
        jobsByRunLoading,
        failedJobRuns,
        workflowRunUrl,
    } = useValues(ciExplorerLogic)
    const { retryFailedJobs } = useActions(ciExplorerLogic)
    const timeline = useMemo(
        () =>
            buildPushTimeline(
                { owner: repoOwner, name: repoName },
                workflowRuns.map((run) => ({
                    id: workflowId(run),
                    run,
                    jobs: jobsByRun[workflowId(run)] ?? [],
                    url: run.runId != null ? workflowRunUrl(run.runId, run.ciEngine ?? null) : undefined,
                })),
                Date.now()
            ),
        [repoOwner, repoName, workflowRuns, jobsByRun, workflowRunUrl]
    )

    if (!activePush) {
        return (
            <div className="py-16 text-center text-sm text-secondary">
                No CI runs are synced for this pull request yet. Runs appear here after the next sync.
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            {failedJobRuns.length > 0 && (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Retry',
                        onClick: retryFailedJobs,
                        loading: jobsByRunLoading,
                        disabledReason: jobsByRunLoading ? 'Loading' : undefined,
                        'data-attr': 'ci-explorer-timeline-retry-jobs',
                    }}
                >
                    Couldn't load jobs for {pluralize(failedJobRuns.length, 'workflow')}
                </LemonBanner>
            )}
            {jobsByRunLoading && (
                <span className="flex items-center gap-1.5 text-xs text-secondary">
                    <Spinner /> Loading jobs
                </span>
            )}
            <CITimeline timeline={timeline} />
        </div>
    )
}
