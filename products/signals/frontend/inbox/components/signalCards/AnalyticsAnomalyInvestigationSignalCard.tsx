import { LemonTag, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import type { AnalyticsAnomalyInvestigationSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a signal's `extra` to the product-analytics anomaly-investigation shape. */
export function isAnalyticsAnomalyInvestigationExtra(
    value: unknown
): value is Record<string, unknown> & AnalyticsAnomalyInvestigationSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.alert_id === 'string' && typeof extra.insight_id === 'string'
}

/** Maps the investigation verdict to a badge, with a fallback for malformed legacy payloads. */
function VerdictBadge({ verdict }: { verdict: AnalyticsAnomalyInvestigationSignalExtraApi['verdict'] }): JSX.Element {
    if (verdict === 'true_positive') {
        return (
            <LemonTag type="danger" size="small">
                True positive
            </LemonTag>
        )
    }
    if (verdict === 'false_positive') {
        return (
            <LemonTag type="muted" size="small">
                False positive
            </LemonTag>
        )
    }
    if (verdict === 'inconclusive') {
        return (
            <LemonTag type="warning" size="small">
                Inconclusive
            </LemonTag>
        )
    }
    return (
        <LemonTag type="danger" size="small">
            Firing
        </LemonTag>
    )
}

/** Inbox signal card for product-analytics anomaly investigations (an anomaly alert firing on an insight). */
export function AnalyticsAnomalyInvestigationSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!isAnalyticsAnomalyInvestigationExtra(signal.extra)) {
        return <SignalCardShell signal={signal}>{null}</SignalCardShell>
    }
    const extra = signal.extra
    const insightLabel = extra.insight_name || extra.insight_short_id || extra.insight_id

    return (
        <SignalCardShell signal={signal} label={extra.alert_name} rightSlot={<VerdictBadge verdict={extra.verdict} />}>
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <p className="text-sm m-0">
                        Anomaly detected on{' '}
                        {extra.insight_short_id ? (
                            <Link
                                to={urls.insightView(extra.insight_short_id as InsightShortId)}
                                className="font-medium"
                            >
                                {insightLabel}
                            </Link>
                        ) : (
                            <span className="font-medium">{insightLabel}</span>
                        )}
                    </p>
                    {extra.detector_type && <p className="text-xs text-tertiary m-0">Detector {extra.detector_type}</p>}
                </div>

                {signal.content && (
                    <LemonMarkdown className="text-sm text-secondary" disableImages>
                        {signal.content}
                    </LemonMarkdown>
                )}

                <div className="flex items-center gap-3 text-xs">
                    <span className="flex-1" />
                    {extra.notebook_short_id && (
                        <Link to={urls.notebook(extra.notebook_short_id)} className="font-medium shrink-0">
                            View investigation
                        </Link>
                    )}
                    <Link to={urls.alert(extra.alert_id)} className="font-medium shrink-0">
                        View alert
                    </Link>
                </div>
            </div>
        </SignalCardShell>
    )
}

export const analyticsAnomalyInvestigationSignalCardEntry: SignalCardEntry = {
    key: 'analytics',
    matches: (signal) => signal.source_product === 'analytics' && isAnalyticsAnomalyInvestigationExtra(signal.extra),
    Component: AnalyticsAnomalyInvestigationSignalCard,
}
