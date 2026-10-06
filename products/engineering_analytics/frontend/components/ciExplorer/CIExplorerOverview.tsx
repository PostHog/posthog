import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { ciExplorerContextLogic } from '../../scenes/ciExplorerContextLogic'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CIExplorerCanvas } from './CIExplorerCanvas'
import { CIExplorerShare } from './CIExplorerShare'
import { CIExplorerTrail } from './CIExplorerTrail'

/** The CI of one commit: where the camera is, its share of the job time on request, and the canvas. */
export function CIExplorerOverview(): JSX.Element {
    const { activePush, selectedHeadSha, logicProps, jobTimeOpen, failedJobRuns, jobsByRunLoading } =
        useValues(ciExplorerLogic)
    const { toggleJobTime, retryFailedJobs } = useActions(ciExplorerLogic)
    if (!activePush) {
        return (
            <div className="py-16 text-center text-sm text-secondary">
                {selectedHeadSha === null
                    ? 'No CI runs are synced for this pull request yet. Runs appear here after the next sync.'
                    : 'No CI runs are synced for this commit. Open Activity to choose another commit.'}
            </div>
        )
    }
    return (
        <BindLogic logic={ciExplorerContextLogic} props={logicProps}>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <CIExplorerTrail />
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    active={jobTimeOpen}
                    aria-expanded={jobTimeOpen}
                    onClick={toggleJobTime}
                    data-attr="ci-explorer-job-time-toggle"
                >
                    Job time
                </LemonButton>
            </div>
            {failedJobRuns.length > 0 && (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Retry',
                        onClick: retryFailedJobs,
                        loading: jobsByRunLoading,
                        disabledReason: jobsByRunLoading ? 'Loading' : undefined,
                        'data-attr': 'ci-explorer-retry-jobs',
                    }}
                >
                    Couldn't load the jobs of {pluralize(failedJobRuns.length, 'workflow')}. Their tiles show no job
                    graph.
                </LemonBanner>
            )}
            {jobTimeOpen && <CIExplorerShare />}
            {/* The canvas takes the height the header leaves, and no less than a readable minimum. */}
            <div
                className={
                    jobTimeOpen
                        ? 'h-[calc(100vh-24rem)] min-h-96 overflow-hidden rounded-lg border border-primary'
                        : 'h-[calc(100vh-20rem)] min-h-96 overflow-hidden rounded-lg border border-primary'
                }
            >
                <CIExplorerCanvas />
            </div>
        </BindLogic>
    )
}
