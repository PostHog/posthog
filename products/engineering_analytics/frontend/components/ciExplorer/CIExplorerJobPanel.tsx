import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import type { WorkflowJobApi } from '../../generated/api.schemas'
import { compactUsd } from '../../lib/format'
import { githubRunUrl } from '../../lib/github'
import type { WorkflowRun } from '../../lib/lifecycle'
import { withCurrentScope } from '../../lib/scope'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { RunConclusionTag } from '../runTables'

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-baseline justify-between gap-4 text-xs">
            <dt className="text-secondary">{label}</dt>
            <dd className="m-0 text-right tabular-nums">{children}</dd>
        </div>
    )
}

/** What is known about the selected job. Steps are not synced yet, so the job is the deepest level. */
export function CIExplorerJobPanel({ job, run }: { job: WorkflowJobApi; run: WorkflowRun }): JSX.Element {
    const { repoOwner, repoName, sourceId, focusLevels, focusedJobFailure } = useValues(ciExplorerLogic)
    const { setFocus } = useActions(ciExplorerLogic)

    return (
        <aside
            className="flex w-72 max-w-full flex-col gap-3 rounded-lg border border-primary bg-surface-primary p-3 shadow-md"
            aria-label="Job details"
        >
            <div className="flex items-start gap-2">
                <h3 className="m-0 min-w-0 flex-1 break-words text-sm font-semibold">{job.name}</h3>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    aria-label="Close job details"
                    onClick={() => setFocus(focusLevels[focusLevels.length - 2]?.id ?? null)}
                    data-attr="ci-explorer-job-panel-close"
                />
            </div>
            <dl className="m-0 flex flex-col gap-1.5">
                <Row label="Status">
                    <RunConclusionTag conclusion={job.conclusion} />
                </Row>
                <Row label="Duration">
                    {job.duration_seconds === null ? 'Running' : humanFriendlyDuration(job.duration_seconds)}
                </Row>
                {job.started_at && (
                    <Row label="Started">
                        <TZLabel time={job.started_at} />
                    </Row>
                )}
                <Row label="Runner">{job.runner_label || 'Unknown'}</Row>
                {job.estimated_cost_usd !== null && (
                    <Row label="Estimated cost">{compactUsd(job.estimated_cost_usd)}</Row>
                )}
            </dl>
            {focusedJobFailure && (
                <pre className="m-0 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded bg-fill-error-tertiary p-3 font-mono text-xs text-danger">
                    {focusedJobFailure.lines.map((line) => line.text).join('\n')}
                </pre>
            )}
            {run.runId !== null && (
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={withCurrentScope(
                            urls.engineeringAnalyticsWorkflowRun(repoOwner, repoName, run.runId, run.ciEngine),
                            sourceId
                        )}
                        data-attr="ci-explorer-open-run"
                    >
                        Open workflow run
                    </LemonButton>
                    {run.ciEngine !== 'depot_ci' && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={`${githubRunUrl(repoOwner, repoName, run.runId)}/job/${job.id}`}
                            targetBlank
                            data-attr="ci-explorer-open-job-github"
                        >
                            View job on GitHub
                        </LemonButton>
                    )}
                </div>
            )}
        </aside>
    )
}
