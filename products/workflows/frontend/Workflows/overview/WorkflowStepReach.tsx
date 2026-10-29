import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { metricsStepUrl } from '../metricsDrillParams'
import { workflowOverviewLogic } from './workflowOverviewLogic'

function ReachRow({
    name,
    count,
    base,
    to,
    failed,
    waiting,
}: {
    name: string
    count: number
    base: number
    to?: string
    failed?: number
    waiting?: number
}): JSX.Element {
    const share = base > 0 ? Math.min(1, count / base) : 0
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2 text-sm">
                <span className="flex min-w-0 items-center gap-2">
                    {to ? (
                        <Link to={to} className="truncate" data-attr="workflow-overview-step-reach-step">
                            {name}
                        </Link>
                    ) : (
                        <span className="truncate font-medium">{name}</span>
                    )}
                    {failed ? (
                        <LemonTag type="danger" size="small">
                            {`${humanFriendlyNumber(failed)} failed`}
                        </LemonTag>
                    ) : null}
                    {waiting ? (
                        <span
                            className="whitespace-nowrap text-xs text-muted"
                            data-attr="workflow-overview-step-reach-waiting"
                        >
                            {`${humanFriendlyNumber(waiting)} waiting now`}
                        </span>
                    ) : null}
                </span>
                <span className="whitespace-nowrap">
                    <span translate="no">{humanFriendlyNumber(count)}</span>
                    {base > 0 ? (
                        <span className="text-muted" translate="no">{` (${percentage(count / base, 1)})`}</span>
                    ) : null}
                </span>
            </div>
            <LemonProgress percent={share * 100} />
        </div>
    )
}

export function WorkflowStepReach({
    id,
    logicKey,
    period = 'in this date range',
    runId,
}: {
    id: string
    logicKey: string
    period?: string
    runId?: string
}): JSX.Element {
    const logic = workflowOverviewLogic({ id, logicKey })
    const { stepReach, stepTotalsLoading, healthTotals, params, stepTotalsFailed, healthTotalsFailed, retrying } =
        useValues(logic)
    const { retry } = useActions(logic)
    const started = healthTotals?.triggered ?? 0

    return (
        <div
            className="flex flex-col gap-3 rounded border bg-surface-primary p-4"
            data-attr="workflow-overview-step-reach"
        >
            <div className="flex flex-col gap-1">
                <h3 className="mb-0 flex items-center gap-1 text-base font-semibold">
                    Step reach
                    <Tooltip title="A run that is waiting at a step counts for that step once it moves on.">
                        <IconInfo className="text-muted" />
                    </Tooltip>
                </h3>
                <span className="text-xs text-muted">
                    {`How many runs got past each step ${period}, as a share of runs started.`}
                </span>
            </div>
            {stepTotalsFailed || healthTotalsFailed ? (
                <span className="flex flex-wrap items-center gap-2 text-sm text-muted">
                    Couldn't load step reach.
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={retry}
                        loading={retrying}
                        data-attr="workflow-overview-step-reach-retry"
                    >
                        Try again
                    </LemonButton>
                </span>
            ) : stepTotalsLoading && !stepReach ? (
                <LemonSkeleton repeat={4} className="h-6" />
            ) : !stepReach || stepReach.length === 0 ? (
                <span className="text-sm text-muted">This workflow has no steps yet.</span>
            ) : (
                <div className="flex flex-col gap-3">
                    <ReachRow name="Started" count={started} base={started} />
                    {stepReach.map(({ action, reached, failed, waiting }) => (
                        <ReachRow
                            key={action.id}
                            name={action.name}
                            count={reached}
                            base={started}
                            failed={failed}
                            waiting={waiting}
                            to={metricsStepUrl(id, action.id, params, runId)}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
