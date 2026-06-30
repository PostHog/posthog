import { useValues } from 'kea'

import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import { SleepingHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { VisionActionRunApi, VisionActionRunStatusEnumApi } from '../../generated/api.schemas'
import { visionActionRunsLogic } from '../visionActionRunsLogic'

const STATUS_TAG: Record<
    VisionActionRunStatusEnumApi,
    { type: 'success' | 'danger' | 'warning' | 'primary'; label: string }
> = {
    completed: { type: 'success', label: 'Completed' },
    failed: { type: 'danger', label: 'Failed' },
    skipped: { type: 'warning', label: 'Skipped' },
    running: { type: 'primary', label: 'Running' },
}

function StatCell({
    title,
    value,
    description,
}: {
    title: string
    value: React.ReactNode
    description?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex-1 min-w-[150px] px-3 py-3 flex flex-col items-center text-center border-border [&:not(:first-child)]:sm:border-l">
            <div className="text-xs font-semibold uppercase text-secondary">{title}</div>
            <div className="text-xl font-semibold leading-tight mt-1">{value}</div>
            {description && <div className="text-xs text-secondary mt-0.5">{description}</div>}
        </div>
    )
}

function RunStats(): JSX.Element {
    const { action, runsCount } = useValues(visionActionRunsLogic)
    const disabled = action?.enabled === false
    return (
        <div className="flex flex-wrap sm:flex-nowrap items-stretch border rounded bg-surface-primary">
            <StatCell title="Total runs" value={humanFriendlyNumber(runsCount)} description="all time" />
            <StatCell
                title="Last run"
                value={
                    action?.last_run_at ? (
                        <TZLabel time={action.last_run_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                    ) : (
                        'Never'
                    )
                }
            />
            <StatCell
                title="Next run"
                value={
                    disabled ? (
                        'N/A'
                    ) : action?.next_run_at ? (
                        <TZLabel time={action.next_run_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                    ) : (
                        '—'
                    )
                }
                description={disabled ? 'Action disabled' : undefined}
            />
        </div>
    )
}

function RunMeta({ run }: { run: VisionActionRunApi }): JSX.Element {
    const tag = STATUS_TAG[run.status]
    const count = run.observation_count
    return (
        <div className="flex items-center gap-2 text-xs text-secondary">
            <LemonTag type={tag.type} size="small">
                {tag.label}
            </LemonTag>
            <TZLabel time={run.scheduled_at ?? run.created_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
            {count > 0 && <span>· Summarized {count === 1 ? '1 observation' : `${count} observations`}</span>}
        </div>
    )
}

function RunCard({ run }: { run: VisionActionRunApi }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3">
            <RunMeta run={run} />
            {run.synthesized_markdown ? (
                // The summary is the point of the run — give it the room.
                <LemonMarkdown className="text-base">{run.synthesized_markdown}</LemonMarkdown>
            ) : (
                <div className="text-muted italic">{run.error_reason || 'No summary was produced for this run.'}</div>
            )}
        </LemonCard>
    )
}

function EmptyRuns(): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center gap-3 py-10">
            <SleepingHog className="w-40 h-40" />
            <h3 className="m-0">Your action is live</h3>
            <p className="text-muted max-w-md">
                Results will show up after its next scheduled run. Once it runs, you'll see the summaries here — check
                back soon.
            </p>
        </div>
    )
}

export function VisionActionRuns(): JSX.Element {
    const { runs, runsLoading } = useValues(visionActionRunsLogic)

    return (
        <div className="flex flex-col gap-4">
            <RunStats />
            {runsLoading && runs.length === 0 ? (
                <div className="flex justify-center p-8">
                    <Spinner className="text-2xl" />
                </div>
            ) : runs.length === 0 ? (
                <EmptyRuns />
            ) : (
                <div className="flex flex-col gap-3">
                    {runs.map((run) => (
                        <RunCard key={run.id} run={run} />
                    ))}
                </div>
            )}
        </div>
    )
}
