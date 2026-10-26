import { useValues } from 'kea'

import { IconCheckCircle, IconExternal, IconWarning } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { CITimingContextApi } from '../../generated/api.schemas'
import { CIContextSelection, deltaPercent, sampleUrl } from '../../lib/ciExplorerContext'
import { oldestSync, providerName } from '../../lib/ciExplorerDetails'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

const MATCH_RULES =
    'Runs of the same workflow and jobs on the same runners. Pull request and merge queue runs are excluded.'

const UNAVAILABLE: Record<NonNullable<CITimingContextApi['unavailable_reason']>, string> = {
    default_branch_unknown: 'Default branch unknown',
    jobs_not_synced: 'Job data not synced',
    not_executed: 'Did not run',
}

function seconds(value: number): string {
    return humanFriendlyDuration(Math.round(value), { maxUnits: 2 })
}

function Fact({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-baseline justify-between gap-4 text-xs">
            <dt className="text-secondary">{label}</dt>
            <dd className="m-0 text-right tabular-nums">{children}</dd>
        </div>
    )
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
                    <dt className="text-xs text-secondary">This run</dt>
                    <dd className="m-0 mt-1 font-mono text-lg">
                        {selection.currentSeconds === null ? selection.statusText : seconds(selection.currentSeconds)}
                    </dd>
                    {selection.currentSeconds !== null && (
                        <dd className="m-0 text-xs text-secondary">{selection.statusText}</dd>
                    )}
                </div>
                {context.average_seconds !== null && (
                    <div>
                        <dt className="text-xs text-secondary">{context.window_days}-day average</dt>
                        <dd className="m-0 mt-1 font-mono text-lg">{seconds(context.average_seconds)}</dd>
                        {delta !== null && (
                            <dd className="m-0 text-xs text-secondary">
                                {delta === 0 ? 'Same' : `${Math.abs(delta)}% ${delta < 0 ? 'faster' : 'slower'}`}
                            </dd>
                        )}
                    </div>
                )}
            </dl>
            {context.recent.length === 0 ? (
                <p className="m-0 text-xs text-secondary">
                    No comparable runs on {context.default_branch} in the last {context.window_days} days
                </p>
            ) : (
                <>
                    <dl className="m-0 flex flex-col gap-1.5">
                        <Fact label="Branch">{context.default_branch}</Fact>
                        <Fact label="Passed runs">
                            <Tooltip title={MATCH_RULES}>
                                <span>
                                    {context.sample_count}
                                    {context.sampled ? ` of latest ${context.runs_scanned}` : ''}
                                </span>
                            </Tooltip>
                        </Fact>
                        {context.identity === 'workflow_name' && <Fact label="Workflow matched by">Name</Fact>}
                    </dl>
                    <h4 className="m-0 text-xs font-semibold">Recent runs</h4>
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
                                            external
                                                ? `Open on ${providerName(sample.ci_engine)} in a new tab`
                                                : undefined
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
                </>
            )}
            {synced && (
                <p className="m-0 text-xs text-tertiary">
                    Synced <TZLabel time={synced} />
                </p>
            )}
        </>
    )
}
