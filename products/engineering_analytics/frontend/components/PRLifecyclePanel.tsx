import { useActions, useValues } from 'kea'

import { IconArrowRight, IconX } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration, pluralize } from 'lib/utils'

import { WorkflowVerdict, summarizeLifecycle } from '../lib/lifecycle'
import { PullRequestRow, engineeringAnalyticsLogic, prKeyOf } from '../scenes/engineeringAnalyticsLogic'

const MAX_LISTED_VERDICTS = 8

function deltaFrom(start: string, end: string): string {
    const seconds = dayjs(end).diff(dayjs(start), 'second')
    return seconds <= 0 ? '<1s' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

function conclusionTagType(conclusion: string): LemonTagType {
    return conclusion === 'failure' || conclusion === 'timed_out' ? 'danger' : 'warning'
}

function Milestone({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <span className="flex items-center gap-1 whitespace-nowrap">
            <span className="font-medium">{label}</span>
            <span className="text-secondary">{children}</span>
        </span>
    )
}

function Separator(): JSX.Element {
    return <IconArrowRight className="shrink-0 text-tertiary" />
}

function VerdictRow({ verdict }: { verdict: WorkflowVerdict }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <IconX className="shrink-0 text-danger" />
            <span className="font-mono text-xs">{verdict.workflow}</span>
            <LemonTag type={conclusionTagType(verdict.conclusion)} size="small">
                {verdict.conclusion.replace('_', ' ')}
            </LemonTag>
            <span className="text-xs text-tertiary">
                <TZLabel time={verdict.at} />
            </span>
        </div>
    )
}

export function PRLifecyclePanel({ row }: { row: PullRequestRow }): JSX.Element {
    const { lifecycles, lifecycleLoadingKeys } = useValues(engineeringAnalyticsLogic)
    const { loadLifecycle } = useActions(engineeringAnalyticsLogic)

    const key = prKeyOf(row)
    const lifecycle = lifecycles[key]

    if (lifecycle === undefined) {
        return (
            <div className="flex flex-col gap-2 py-3">
                <LemonSkeleton className="h-4 w-96" />
                <LemonSkeleton className="h-4 w-64" />
            </div>
        )
    }

    if (lifecycle === null) {
        return (
            <div className="flex items-center gap-3 py-3">
                <span className="text-secondary">Couldn't load this pull request's lifecycle.</span>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => loadLifecycle({ row, force: true })}
                    loading={!!lifecycleLoadingKeys[key]}
                >
                    Retry
                </LemonButton>
            </div>
        )
    }

    const summary = summarizeLifecycle(lifecycle.events)
    const openedAt = summary.openedAt ?? row.createdAt
    const listedVerdicts = summary.notPassing.slice(0, MAX_LISTED_VERDICTS)
    const extraVerdicts = summary.notPassing.length - listedVerdicts.length

    // Chronological, not fixed, order: a PR's head-SHA runs can start (and finish) after the
    // merge, and the arrow flow should read true to the timestamps.
    const milestones: { at: string; node: JSX.Element }[] = [
        {
            at: openedAt,
            node: (
                <Milestone label="Opened">
                    <TZLabel time={openedAt} />
                </Milestone>
            ),
        },
    ]
    if (summary.firstCiStartedAt) {
        milestones.push({
            at: summary.firstCiStartedAt,
            node: <Milestone label="First CI run">+{deltaFrom(openedAt, summary.firstCiStartedAt)}</Milestone>,
        })
    }
    if (summary.lastCiFinishedAt) {
        milestones.push({
            at: summary.lastCiFinishedAt,
            node: <Milestone label="Last CI verdict">+{deltaFrom(openedAt, summary.lastCiFinishedAt)}</Milestone>,
        })
    }
    if (summary.mergedAt) {
        milestones.push({
            at: summary.mergedAt,
            node: <Milestone label="Merged">+{deltaFrom(openedAt, summary.mergedAt)}</Milestone>,
        })
    } else if (summary.closedAt) {
        milestones.push({
            at: summary.closedAt,
            node: <Milestone label="Closed without merging">+{deltaFrom(openedAt, summary.closedAt)}</Milestone>,
        })
    } else {
        // '￿' sorts after any ISO timestamp, keeping the open-ended milestone last.
        milestones.push({
            at: '￿',
            node: <Milestone label="Still open">{deltaFrom(openedAt, dayjs().toISOString())} and counting</Milestone>,
        })
    }
    milestones.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))

    return (
        <div className="flex flex-col gap-3 py-3 pr-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                {milestones.map((milestone, index) => (
                    <span key={index} className="flex items-center gap-3">
                        {index > 0 && <Separator />}
                        {milestone.node}
                    </span>
                ))}
            </div>

            {summary.passed + summary.notPassing.length + summary.unsettled === 0 ? (
                <div className="text-xs text-secondary">No CI runs on the head commit yet.</div>
            ) : (
                <div className="flex flex-col gap-1.5">
                    {listedVerdicts.map((verdict, index) => (
                        <VerdictRow key={`${verdict.workflow}-${index}`} verdict={verdict} />
                    ))}
                    {extraVerdicts > 0 && (
                        <div className="text-xs text-secondary">
                            + {pluralize(extraVerdicts, 'more run')} not passing
                        </div>
                    )}
                    <div className="text-xs text-secondary">
                        {pluralize(summary.passed, 'run')} passed
                        {summary.unsettled > 0 && <> · {summary.unsettled} still running</>}
                    </div>
                </div>
            )}

            <div className="text-xs text-tertiary">
                CI events on the head commit only — review and comment activity isn't tracked yet.
            </div>
        </div>
    )
}
