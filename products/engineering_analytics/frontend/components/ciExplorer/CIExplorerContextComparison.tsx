import { useValues } from 'kea'

import { IconCheckCircle, IconExternal, IconWarning } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'

import type { CITimingContextApi } from '../../generated/api.schemas'
import { CIContextSelection, deltaPercent, sampleUrl } from '../../lib/ciExplorerContext'
import { oldestSync, providerName } from '../../lib/ciExplorerDetails'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

const MATCH_RULES =
    'A run matches when it has the same provider, the same workflow, and jobs with the same names and runner labels. A workflow or a matrix also needs the same set of jobs to have run. Pull request runs and merge queue runs are left out. Only passed runs enter the average.'

const UNAVAILABLE: Record<NonNullable<CITimingContextApi['unavailable_reason']>, string> = {
    default_branch_unknown:
        'The default branch of this repository is not known yet, so there is nothing to compare with.',
    jobs_not_synced: 'Job data is not synced for this repository.',
    not_executed: 'This selection did not run, so there is nothing to compare.',
}

function seconds(value: number | null): string {
    return value === null ? 'No data' : humanFriendlyDuration(Math.round(value), { maxUnits: 2 })
}

/** The answer of the Context tab: the selection's duration beside its average, and the runs behind the average. */
export function CIExplorerContextComparison({
    selection,
    context,
}: {
    selection: CIContextSelection
    context: CITimingContextApi
}): JSX.Element {
    const { repoOwner, repoName, workflowRunUrl } = useValues(ciExplorerLogic)
    const delta = deltaPercent(selection, context)
    const synced = oldestSync(context.runs_synced_at, context.jobs_synced_at)

    if (context.unavailable_reason) {
        return <p className="m-0 text-xs text-secondary">{UNAVAILABLE[context.unavailable_reason]}</p>
    }
    return (
        <>
            <dl className="m-0 grid grid-cols-2 gap-4">
                <div>
                    <dt className="text-xs text-secondary">Current</dt>
                    <dd className="m-0 mt-1 font-mono text-lg">{seconds(selection.currentSeconds)}</dd>
                </div>
                <div>
                    <dt className="text-xs text-secondary">
                        {context.window_days}d average{context.sampled ? ' (sample)' : ''}
                    </dt>
                    <dd className="m-0 mt-1 font-mono text-lg">{seconds(context.average_seconds)}</dd>
                </div>
            </dl>
            <p className="m-0 text-sm">
                {delta === null
                    ? selection.statusText
                    : delta === 0
                      ? 'Same as the average'
                      : `${Math.abs(delta)}% ${delta < 0 ? 'below' : 'above'} average`}
            </p>
            <Tooltip title={MATCH_RULES}>
                <p className="m-0 text-xs text-secondary">
                    {context.default_branch}, last {context.window_days} days.{' '}
                    {pluralize(context.sample_count, 'passed run')} of {context.runs_scanned} checked
                    {context.sampled ? `, the newest ${context.runs_scanned} only` : ''}.
                    {context.identity === 'workflow_name' ? ' Workflow matched by name.' : ''}
                </p>
            </Tooltip>
            <h4 className="m-0 text-xs font-semibold">Recent matching runs</h4>
            {context.recent.length ? (
                <ul className="m-0 flex list-none flex-col p-0">
                    {context.recent.map((sample) => {
                        const { url, external } = sampleUrl(
                            repoOwner,
                            repoName,
                            sample,
                            workflowRunUrl(sample.run_id, sample.ci_engine)
                        )
                        return (
                            <li key={`${sample.run_id}:${sample.run_attempt}`} className="border-b border-primary">
                                <Link
                                    to={url}
                                    target={external ? '_blank' : undefined}
                                    targetBlankIcon={false}
                                    subtle
                                    className="flex min-h-9 items-center gap-2 text-xs"
                                    title={
                                        external ? `Open on ${providerName(sample.ci_engine)} in a new tab` : undefined
                                    }
                                    data-attr="ci-explorer-context-run"
                                >
                                    {sample.status === 'success' ? (
                                        <IconCheckCircle className="text-success" aria-label="Passed" />
                                    ) : (
                                        <IconWarning className="text-danger" aria-label="Failed" />
                                    )}
                                    <span className="flex-1">
                                        <TZLabel time={sample.completed_at} />
                                    </span>
                                    <b className="font-mono font-normal">{seconds(sample.duration_seconds)}</b>
                                    {external && <IconExternal className="text-tertiary" />}
                                </Link>
                            </li>
                        )
                    })}
                </ul>
            ) : (
                <p className="m-0 text-xs text-secondary">
                    No matching run on {context.default_branch} in the last {context.window_days} days.
                </p>
            )}
            <p className="m-0 text-xs text-tertiary">
                {synced ? (
                    <>
                        Data synced <TZLabel time={synced} />
                    </>
                ) : (
                    'Sync time unknown'
                )}
            </p>
        </>
    )
}
