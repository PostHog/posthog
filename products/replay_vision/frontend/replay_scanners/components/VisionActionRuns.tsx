import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { SleepingHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { VisionActionRunListApi } from '../../generated/api.schemas'
import { VisionActionModeEnumApi } from '../../generated/api.schemas'
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
    // Quiet alert checks (condition not met) don't appear in the run list, so for alerts the time
    // cells speak in terms of checks: "last checked" can be much more recent than the newest row.
    const isAlert = action?.mode === VisionActionModeEnumApi.Alert
    // every_match rides each scanner sweep; on_breach thresholds are re-checked hourly.
    const everyMatch = action?.alert_config?.frequency === 'every_match'
    return (
        <div className="flex flex-wrap sm:flex-nowrap items-stretch border rounded bg-surface-primary">
            <StatCell
                title={isAlert ? 'Alerts' : 'Total runs'}
                value={humanFriendlyNumber(runsCount)}
                description="all time"
            />
            <StatCell
                title={isAlert ? 'Last checked' : 'Last run'}
                value={
                    action?.last_run_at ? (
                        <TZLabel time={action.last_run_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                    ) : (
                        'Never'
                    )
                }
                description={
                    isAlert ? (everyMatch ? 'checked every few minutes' : 'checked about every hour') : undefined
                }
            />
            <StatCell
                title={isAlert ? 'Next check' : 'Next run'}
                value={
                    disabled ? (
                        'N/A'
                    ) : isAlert && everyMatch ? (
                        // every_match checks ride each sweep; the rrule cursor is vestigial there and
                        // showing it would overstate the gap between checks. on_breach follows the cursor.
                        'Within minutes'
                    ) : action?.next_run_at ? (
                        <TZLabel time={action.next_run_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                    ) : (
                        '—'
                    )
                }
                description={disabled ? (isAlert ? 'Alert disabled' : 'Action disabled') : undefined}
            />
        </div>
    )
}

function EmptyRuns(): JSX.Element {
    const { action } = useValues(visionActionRunsLogic)
    const isAlert = action?.mode === VisionActionModeEnumApi.Alert
    const everyMatch = action?.alert_config?.frequency === 'every_match'
    return (
        <div className="flex flex-col items-center text-center gap-3 py-10">
            <SleepingHog className="w-40 h-40" />
            <h3 className="m-0">{isAlert ? 'Your alert is live' : 'Your action is live'}</h3>
            <p className="text-muted max-w-md">
                {isAlert
                    ? `Checks run ${everyMatch ? 'every few minutes' : 'about every hour'}. When the condition is met, the alert and its matching observations show up here.`
                    : "Results will show up after its next scheduled run. Once it runs, you'll see the summaries here — check back soon."}
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
        {
            key: 'actions',
            width: 0,
            render: (_, run) => (
                <LemonButton
                    size="small"
                    type="secondary"
                    to={urls.replayVisionActionRun(actionId, run.id)}
                    data-attr="vision-action-run-view"
                >
                    View
                </LemonButton>
            ),
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
                <LemonTable
                    columns={columns}
                    dataSource={runs}
                    rowKey="id"
                    rowClassName="cursor-pointer"
                    onRow={(run) => ({
                        onClick: () => router.actions.push(urls.replayVisionActionRun(actionId, run.id)),
                    })}
                    data-attr="vision-action-runs-table"
                />
            )}
        </div>
    )
}
