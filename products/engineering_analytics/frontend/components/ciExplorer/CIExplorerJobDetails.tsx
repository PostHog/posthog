import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowJobApi } from '../../generated/api.schemas'
import { providerName, statusLabel } from '../../lib/ciExplorerDetails'
import { compactUsd } from '../../lib/format'
import { githubJobUrl } from '../../lib/github'
import { WorkflowRun, isDecisiveFailure } from '../../lib/lifecycle'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CIExplorerChips } from './CIExplorerChips'
import { CIExplorerFailureLog } from './CIExplorerFailureLog'
import { CIExplorerProviderMark } from './CIExplorerProviderMark'

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-baseline justify-between gap-4 text-xs">
            <dt className="text-secondary">{label}</dt>
            <dd className="m-0 text-right tabular-nums">{children}</dd>
        </div>
    )
}

/** What is known about the selected job: how it ended, where it ran, what it cost, and why it failed. */
export function CIExplorerJobDetails({ job, run }: { job: WorkflowJobApi; run: WorkflowRun }): JSX.Element {
    const { repoOwner, repoName, focusedJobInsights, workflowRunUrl } = useValues(ciExplorerLogic)

    return (
        <>
            <h3 className="m-0 break-words text-sm font-semibold">{job.name}</h3>
            <dl className="m-0 flex flex-col gap-1.5">
                <Row label="Status">{statusLabel(job.conclusion)}</Row>
                <Row label="Elapsed">
                    {job.duration_seconds === null ? 'Running' : humanFriendlyDuration(job.duration_seconds)}
                </Row>
                {job.started_at && (
                    <Row label="Started">
                        <TZLabel time={job.started_at} />
                    </Row>
                )}
                <Row label="Provider">
                    <span className="inline-flex items-center gap-1.5">
                        <CIExplorerProviderMark engine={job.ci_engine} />
                        {providerName(job.ci_engine)}
                    </span>
                </Row>
                <Row label="Runner">{job.runner_label || 'Unknown'}</Row>
                {job.estimated_cost_usd !== null && (
                    <Row label="Estimated cost">{compactUsd(job.estimated_cost_usd)}</Row>
                )}
            </dl>
            {isDecisiveFailure(job.conclusion) && <CIExplorerFailureLog />}
            {focusedJobInsights && focusedJobInsights.job.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                    <CIExplorerChips badges={focusedJobInsights.job} />
                </div>
            )}
            {run.runId !== null && (
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={workflowRunUrl(run.runId, run.ciEngine)}
                        data-attr="ci-explorer-open-run"
                    >
                        Open workflow run
                    </LemonButton>
                    {run.ciEngine !== 'depot_ci' && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={githubJobUrl(repoOwner, repoName, run.runId, job.id)}
                            targetBlank
                            data-attr="ci-explorer-open-job-github"
                        >
                            Open job on GitHub
                        </LemonButton>
                    )}
                </div>
            )}
        </>
    )
}
