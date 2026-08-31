import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { OutcomeReadoutHistoryDTOApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionPulseArtifacts } from './SubscriptionPulseArtifacts'

const OUTCOME_VERDICT: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'default' }> = {
    improved: { label: 'Improved', type: 'success' },
    flat: { label: 'Flat', type: 'default' },
    regressed: { label: 'Regressed', type: 'danger' },
    inconclusive: { label: 'Inconclusive', type: 'warning' },
}

const INCONCLUSIVE_REASON: Record<string, string> = {
    permissions_lost: 'PostHog no longer has access to the measurement source. Restore access before the next readout.',
    retry_exhausted:
        'PostHog could not measure this outcome after two attempts. Check the source before the next readout.',
}

export function SubscriptionPulseOutcomeReadout({ readout }: { readout: OutcomeReadoutHistoryDTOApi }): JSX.Element {
    const verdict = OUTCOME_VERDICT[readout.verdict] ?? { label: 'Inconclusive', type: 'warning' as const }
    return (
        <div className="rounded border bg-bg-light p-3 flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="font-medium">{readout.recommendation_title}</div>
                <LemonTag type={verdict.type}>{verdict.label}</LemonTag>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-secondary">
                <span>
                    <span className="font-medium text-primary">Measurement</span>: {readout.metric_name} (
                    {readout.metric_unit})
                </span>
                <span>
                    <span className="font-medium text-primary">Baseline</span>: {readout.baseline_value}
                </span>
                {readout.observed_value !== null ? (
                    <span>
                        <span className="font-medium text-primary">Observed</span>: {readout.observed_value}
                    </span>
                ) : null}
                {readout.absolute_delta !== null ? (
                    <span>
                        <span className="font-medium text-primary">Absolute movement</span>: {readout.absolute_delta}
                    </span>
                ) : null}
                {readout.relative_delta !== null ? (
                    <span>
                        <span className="font-medium text-primary">Relative movement</span>: {readout.relative_delta}%
                    </span>
                ) : null}
                {readout.confidence !== null ? <span>Confidence: {readout.confidence}</span> : null}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-secondary">
                <span>
                    <span className="font-medium text-primary">Baseline window</span>:{' '}
                    <TZLabel time={readout.baseline_from} formatDate="MMM D, YYYY" formatTime="HH:mm" /> –{' '}
                    <TZLabel time={readout.baseline_to} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                </span>
                {readout.observed_from && readout.observed_to ? (
                    <span>
                        <span className="font-medium text-primary">Observed window</span>:{' '}
                        <TZLabel time={readout.observed_from} formatDate="MMM D, YYYY" formatTime="HH:mm" /> –{' '}
                        <TZLabel time={readout.observed_to} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                    </span>
                ) : null}
            </div>
            <SubscriptionPulseArtifacts artifacts={readout.artifacts} linkLabel="View source" />
            {readout.failure_code ? (
                <div className="text-warning text-xs">
                    {INCONCLUSIVE_REASON[readout.failure_code] ??
                        'PostHog could not complete this readout. Check the source before the next readout.'}
                </div>
            ) : null}
        </div>
    )
}
