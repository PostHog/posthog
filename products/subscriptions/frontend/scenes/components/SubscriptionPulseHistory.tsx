import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ProactiveHistoryEntryApi } from 'products/subscriptions/frontend/generated/api.schemas'

type PulseHistoryProps = {
    history: ProactiveHistoryEntryApi[] | null
    loading: boolean
    hasError: boolean
}

function artifactTagType(status: string): 'default' | 'success' | 'danger' | 'warning' {
    if (status === 'adopted') {
        return 'success'
    }
    if (status === 'failed') {
        return 'danger'
    }
    if (status === 'preparing') {
        return 'warning'
    }
    return 'default'
}

function outcomeTagType(status: string): 'default' | 'success' | 'danger' | 'warning' {
    if (status === 'improved') {
        return 'success'
    }
    if (status === 'regressed') {
        return 'danger'
    }
    if (status === 'inconclusive' || status === 'unavailable') {
        return 'warning'
    }
    return 'default'
}

function titleCase(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, ' ')
}

function preparedWorkLabel(kind: string): string {
    return kind === 'experiment_draft' ? 'Experiment draft' : 'Draft pull request'
}

function preparedWorkLinkLabel(kind: string): string {
    return kind === 'experiment_draft' ? 'View experiment' : 'View draft PR'
}

function formatDecimal(value: string): string {
    const normalized = value.replace(/(\.\d*?[1-9])0+$|\.0+$/, '$1')
    return normalized === '-0' ? '0' : normalized
}

export function SubscriptionPulseHistory({ history, loading, hasError }: PulseHistoryProps): JSX.Element {
    return (
        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="subscription-pulse-history-heading">
            <div>
                <h2 id="subscription-pulse-history-heading" className="text-lg font-semibold">
                    Follow-up recommendations
                </h2>
                <p className="m-0 text-sm text-secondary">
                    Recommendations, prepared work, and metric movement after adoption.
                </p>
            </div>
            {loading ? (
                <LemonCard hoverEffect={false} className="space-y-3 p-4" data-attr="subscription-pulse-history-loading">
                    <LemonSkeleton className="h-4 w-2/5" />
                    <LemonSkeleton className="h-3 w-full" />
                    <LemonSkeleton className="h-3 w-4/5" />
                </LemonCard>
            ) : hasError ? (
                <LemonBanner type="error" data-attr="subscription-pulse-history-error">
                    Could not load follow-up recommendations. Refresh the page and try again.
                </LemonBanner>
            ) : history && history.length > 0 ? (
                <div className="grid min-w-0 gap-3">
                    {history.map((entry) => {
                        const { artifact, outcome } = entry
                        const metricValues =
                            outcome?.baseline_value !== null &&
                            outcome?.baseline_value !== undefined &&
                            outcome.observed_value !== null &&
                            outcome.delta !== null
                                ? `Baseline ${formatDecimal(outcome.baseline_value)}, observed ${formatDecimal(
                                      outcome.observed_value
                                  )}, delta ${formatDecimal(outcome.delta)}`
                                : null
                        return (
                            <LemonCard
                                key={`${entry.delivery_id}-${entry.recommendation_title}`}
                                hoverEffect={false}
                                className="min-w-0 space-y-3 p-4"
                                data-attr="subscription-pulse-history-entry"
                            >
                                <div className="min-w-0 space-y-1">
                                    <h3 className="text-sm font-semibold">{entry.recommendation_title}</h3>
                                    {entry.why_now ? (
                                        <p className="m-0 text-sm text-secondary">{entry.why_now}</p>
                                    ) : null}
                                </div>
                                {entry.citations.length > 0 ? (
                                    <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-sm">
                                        <span className="text-secondary">Evidence:</span>
                                        {entry.citations.map((citation, index) =>
                                            citation.url ? (
                                                <LemonButton
                                                    key={`${citation.title}-${index}`}
                                                    type="tertiary"
                                                    size="xsmall"
                                                    to={citation.url}
                                                    targetBlank
                                                >
                                                    {citation.title}
                                                </LemonButton>
                                            ) : (
                                                <span key={`${citation.title}-${index}`}>{citation.title}</span>
                                            )
                                        )}
                                    </div>
                                ) : null}
                                {artifact ? (
                                    <div className="flex min-w-0 flex-col gap-1 text-sm">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className="font-medium">{preparedWorkLabel(artifact.kind)}</span>
                                            <LemonTag type={artifactTagType(artifact.status)}>
                                                {titleCase(artifact.status)}
                                            </LemonTag>
                                            {artifact.url ? (
                                                <LemonButton
                                                    type="tertiary"
                                                    size="xsmall"
                                                    to={artifact.url}
                                                    targetBlank
                                                >
                                                    {preparedWorkLinkLabel(artifact.kind)}
                                                </LemonButton>
                                            ) : null}
                                        </div>
                                        {artifact.prepared_at ? (
                                            <span className="text-secondary">
                                                Prepared <TZLabel time={artifact.prepared_at} />
                                            </span>
                                        ) : null}
                                        {artifact.adopted_at ? (
                                            <span className="text-secondary">
                                                Adopted <TZLabel time={artifact.adopted_at} />
                                            </span>
                                        ) : null}
                                    </div>
                                ) : null}
                                {outcome ? (
                                    <div className="flex min-w-0 flex-col gap-1 text-sm">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className="font-medium">Metric movement after adoption</span>
                                            <LemonTag type={outcomeTagType(outcome.status)}>
                                                {titleCase(outcome.status)}
                                            </LemonTag>
                                            {outcome.metric_name ? (
                                                <span className="text-secondary">{outcome.metric_name}</span>
                                            ) : null}
                                        </div>
                                        {outcome.direction && outcome.expected_metric_movement ? (
                                            <span className="text-secondary">
                                                Expected: {titleCase(outcome.direction)}{' '}
                                                {outcome.expected_metric_movement}
                                            </span>
                                        ) : null}
                                        {metricValues ? <span>{metricValues}</span> : null}
                                        {outcome.baseline_from && outcome.baseline_to ? (
                                            <span className="text-secondary">
                                                Baseline window: {outcome.baseline_from} to {outcome.baseline_to}
                                            </span>
                                        ) : null}
                                        {outcome.observed_from && outcome.observed_to ? (
                                            <span className="text-secondary">
                                                Observed window: <TZLabel time={outcome.observed_from} /> to{' '}
                                                <TZLabel time={outcome.observed_to} />
                                            </span>
                                        ) : null}
                                        {outcome.status === 'pending' && outcome.due_at ? (
                                            <span className="text-secondary">
                                                Readout due <TZLabel time={outcome.due_at} />
                                            </span>
                                        ) : null}
                                    </div>
                                ) : null}
                            </LemonCard>
                        )
                    })}
                </div>
            ) : (
                <LemonCard
                    hoverEffect={false}
                    className="p-4 text-sm text-secondary"
                    data-attr="subscription-pulse-history-empty"
                >
                    No follow-up recommendations yet.
                </LemonCard>
            )}
        </section>
    )
}
