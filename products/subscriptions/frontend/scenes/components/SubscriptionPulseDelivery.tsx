import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import type {
    ArtifactLinkDTOApi,
    PulseRunHistoryDTOApi,
    RunActionHistoryDTOApi,
} from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionPulseArtifacts } from './SubscriptionPulseArtifacts'
import { isAdviceAction, preparedArtifacts } from './subscriptionPulseDeliveryUtils'
import { SubscriptionPulseLifecycleTags } from './SubscriptionPulseLifecycleTags'
import { SubscriptionPulseOperationalDetails } from './SubscriptionPulseOperationalDetails'
import { SubscriptionPulseOutcomeReadout } from './SubscriptionPulseOutcomeReadout'

export type SubscriptionPulseDeliveryProps = {
    run: PulseRunHistoryDTOApi
    decisionLoadingIds: Readonly<Record<string, true>>
    onDecision?: (actionId: string, decision: 'adopted' | 'dismissed') => void
}

const RUN_STATUS: Record<string, { label: string; type: 'success' | 'danger' | 'warning' | 'default' }> = {
    pending: { label: 'Pending', type: 'default' },
    analyzing: { label: 'Analyzing', type: 'default' },
    reserving: { label: 'Preparing', type: 'default' },
    executing: { label: 'In progress', type: 'default' },
    completed: { label: 'Completed', type: 'success' },
    partial: { label: 'Partial', type: 'warning' },
    failed: { label: 'Failed', type: 'danger' },
    cancelled: { label: 'Cancelled', type: 'warning' },
    skipped: { label: 'Skipped', type: 'default' },
}

const ACTION_STATUS: Record<string, string> = {
    proposed: 'Recommended',
    selected: 'Selected',
    executing: 'In progress',
    completed: 'Completed',
    failed: 'Failed',
    skipped: 'Skipped',
}

function expectedMovement(action: RunActionHistoryDTOApi): string | null {
    const bounds = [action.expected_change_lower, action.expected_change_upper].filter((value): value is string =>
        Boolean(value)
    )
    if (bounds.length === 0) {
        return null
    }
    const direction =
        action.metric_direction === 'increase' ? 'higher' : action.metric_direction === 'decrease' ? 'lower' : 'steady'
    const metric = action.metric_name ?? 'Metric'
    if (action.expected_change_type === 'relative_percent') {
        return `${metric}: ${bounds.map((value) => `${value}%`).join(' to ')} ${direction}`
    }
    if (action.metric_unit === 'percent') {
        return `${metric}: ${bounds.join(' to ')} percentage points ${direction}`
    }
    const unit =
        action.metric_unit === 'count'
            ? 'events'
            : action.metric_unit === 'ratio'
              ? 'ratio points'
              : action.metric_unit === 'currency'
                ? 'currency units'
                : action.metric_unit === 'duration'
                  ? 'duration units'
                  : 'units'
    return `${metric}: ${bounds.join(' to ')} ${unit} ${direction}`
}

function runStatus(run: PulseRunHistoryDTOApi): { label: string; type: 'success' | 'danger' | 'warning' | 'default' } {
    if (run.failure_code === 'finalization_timeout' || run.failure_code === 'pulse_timed_out') {
        return { label: 'Timed out', type: 'warning' }
    }
    return RUN_STATUS[run.status] ?? { label: 'Unknown', type: 'default' }
}

function PulseAction({
    action,
    artifacts,
    decisionLoadingIds,
    onDecision,
}: {
    action: RunActionHistoryDTOApi
    artifacts: ArtifactLinkDTOApi[]
    decisionLoadingIds: Readonly<Record<string, true>>
    onDecision?: (actionId: string, decision: 'adopted' | 'dismissed') => void
}): JSX.Element {
    const loading = Boolean(decisionLoadingIds[action.id])
    const label = ACTION_STATUS[action.status] ?? 'Unknown'
    const movement = expectedMovement(action)
    const adviceOnly = isAdviceAction(action) && action.artifacts.length === 0 && action.adoption_status === 'pending'
    return (
        <div className="rounded border bg-bg-light p-3 flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <div className="font-medium">
                        {action.rank}. {action.title}
                    </div>
                    <div className="text-secondary text-xs">{label}</div>
                </div>
                {adviceOnly ? (
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="primary"
                            size="small"
                            loading={loading}
                            disabledReason={loading ? 'Saving…' : null}
                            onClick={() => onDecision?.(action.id, 'adopted')}
                            disabled={!onDecision}
                            data-attr={`pulse-action-adopt-${action.id}`}
                        >
                            {loading ? 'Saving…' : 'Adopt'}
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={loading}
                            disabledReason={loading ? 'Saving…' : null}
                            onClick={() => onDecision?.(action.id, 'dismissed')}
                            disabled={!onDecision}
                            data-attr={`pulse-action-dismiss-${action.id}`}
                        >
                            {loading ? 'Saving…' : 'Dismiss'}
                        </LemonButton>
                    </div>
                ) : null}
            </div>
            <div>{action.rationale}</div>
            <div className="text-secondary">Expected impact: {action.expected_impact}</div>
            <SubscriptionPulseLifecycleTags action={action} />
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-secondary">
                {action.why_now ? (
                    <span>
                        <span className="font-medium text-primary">Why now</span>: {action.why_now}
                    </span>
                ) : null}
                {action.confidence !== null ? (
                    <span>
                        <span className="font-medium text-primary">Confidence</span>: {action.confidence}
                    </span>
                ) : null}
                {action.effort ? <LemonTag type="default">Effort: {action.effort}</LemonTag> : null}
                {movement ? (
                    <span>
                        <span className="font-medium text-primary">Expected movement</span>: {movement}
                    </span>
                ) : null}
                {action.baseline_value !== null ? (
                    <span>
                        <span className="font-medium text-primary">Baseline</span>: {action.baseline_value}
                    </span>
                ) : null}
                {action.readout_after_days && !action.next_readout_at ? (
                    <span>Readout {action.readout_after_days} days after adoption</span>
                ) : null}
            </div>
            <SubscriptionPulseArtifacts artifacts={artifacts} />
        </div>
    )
}

export function SubscriptionPulseDelivery({
    run,
    decisionLoadingIds,
    onDecision,
}: SubscriptionPulseDeliveryProps): JSX.Element {
    const status = runStatus(run)
    const actions = [...run.actions].sort((left, right) => left.rank - right.rank)
    const recommendations = actions.filter(isAdviceAction)
    const preparedActions = actions.filter((action) => !isAdviceAction(action) && preparedArtifacts(action).length > 0)
    return (
        <div className="flex flex-col gap-3 rounded border p-3" data-attr="subscription-pulse-delivery">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-secondary">Pulse</div>
                <LemonTag type={status.type}>{status.label}</LemonTag>
            </div>
            {run.readouts.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold">Outcome readouts</h3>
                    {run.readouts.map((readout) => (
                        <SubscriptionPulseOutcomeReadout key={readout.id} readout={readout} />
                    ))}
                </section>
            ) : null}
            {recommendations.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold">New recommendations</h3>
                    {recommendations.map((action) => (
                        <PulseAction
                            key={action.id}
                            action={action}
                            artifacts={[]}
                            decisionLoadingIds={decisionLoadingIds}
                            onDecision={onDecision}
                        />
                    ))}
                </section>
            ) : null}
            {preparedActions.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold">Prepared artifacts</h3>
                    {preparedActions.map((action) => (
                        <PulseAction
                            key={action.id}
                            action={action}
                            artifacts={preparedArtifacts(action)}
                            decisionLoadingIds={decisionLoadingIds}
                            onDecision={onDecision}
                        />
                    ))}
                </section>
            ) : null}
            {run.readouts.length === 0 && actions.length === 0 ? (
                <div className="text-secondary">No recommendations this time.</div>
            ) : null}
            <SubscriptionPulseOperationalDetails run={run} actions={actions} />
        </div>
    )
}
