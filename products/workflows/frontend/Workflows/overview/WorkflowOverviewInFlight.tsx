import { useValues } from 'kea'

import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { workflowOverviewLogic } from './workflowOverviewLogic'

const MAX_STEPS = 5

export function WorkflowOverviewInFlight({ id, logicKey }: { id: string; logicKey: string }): JSX.Element {
    const { inFlight, inFlightLoading, inFlightSteps } = useValues(workflowOverviewLogic({ id, logicKey }))
    const count = inFlight?.count ?? null
    const positionUnknown = inFlight?.position_unknown ?? 0

    return (
        <div
            className="flex flex-col gap-3 rounded border bg-surface-primary p-4"
            data-attr="workflow-overview-in-flight"
        >
            <div className="flex flex-col gap-1">
                <h3 className="mb-0 text-base font-semibold">In the workflow now</h3>
                <span className="text-xs text-muted">
                    People partway through, waiting on a step or being processed.
                </span>
            </div>
            {inFlightLoading && !inFlight ? (
                <LemonSkeleton className="h-16" />
            ) : count === null ? (
                <span className="text-sm text-muted">
                    We couldn't count people in the workflow right now. Try again later.
                </span>
            ) : (
                <>
                    <span className="text-3xl font-semibold">{humanFriendlyNumber(count)}</span>
                    {inFlightSteps.length > 0 ? (
                        <div className="flex flex-col gap-1 text-sm">
                            {inFlightSteps.slice(0, MAX_STEPS).map(({ action, count: stepCount }) => (
                                <div key={action.id} className="flex items-center justify-between gap-2">
                                    <Link
                                        to={`${urls.workflow(id, 'workflow')}?node=${encodeURIComponent(action.id)}`}
                                        className="truncate"
                                        data-attr="workflow-overview-in-flight-step"
                                    >
                                        {action.name}
                                    </Link>
                                    <span className="whitespace-nowrap text-secondary">
                                        {humanFriendlyNumber(stepCount)}
                                    </span>
                                </div>
                            ))}
                            {inFlightSteps.length > MAX_STEPS ? (
                                <span className="text-xs text-muted">
                                    {`And ${inFlightSteps.length - MAX_STEPS} more steps`}
                                </span>
                            ) : null}
                        </div>
                    ) : count === 0 ? (
                        <span className="text-sm text-muted">No one is partway through right now.</span>
                    ) : null}
                    {positionUnknown > 0 ? (
                        <span className="text-xs text-muted">
                            {humanFriendlyNumber(positionUnknown)} of them are between steps.
                        </span>
                    ) : null}
                </>
            )}
        </div>
    )
}
