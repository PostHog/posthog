import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { SleepingHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { VisionActionRunListApi } from '../../generated/api.schemas'
import { visionActionRunsLogic } from '../visionActionRunsLogic'
import { RunStatusTag } from '../visionActionRunStatus'
import { visionActionSceneLogic } from '../visionActionSceneLogic'

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
    const { actionId } = useValues(visionActionSceneLogic)

    const columns: LemonTableColumns<VisionActionRunListApi> = [
        {
            title: 'When',
            key: 'when',
            render: (_, run) => (
                <Link className="font-semibold" to={urls.replayVisionActionRun(actionId, run.id)}>
                    <TZLabel time={run.scheduled_at ?? run.created_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                </Link>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, run) => <RunStatusTag status={run.status} reason={run.error_reason} />,
        },
        {
            title: 'Observations',
            key: 'observations',
            render: (_, run) => <span className="text-sm">{run.observation_count}</span>,
        },
    ]

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
                <LemonTable columns={columns} dataSource={runs} rowKey="id" data-attr="vision-action-runs-table" />
            )}
        </div>
    )
}
