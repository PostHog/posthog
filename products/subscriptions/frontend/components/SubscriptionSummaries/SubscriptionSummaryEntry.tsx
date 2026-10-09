import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { SubscriptionApi, SubscriptionSummaryApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { TARGET_TYPE_LABEL } from '../../scenes/components/subscriptionLabels'

export function SubscriptionSummaryEntry({ summary }: { summary: SubscriptionSummaryApi }): JSX.Element {
    const channel = TARGET_TYPE_LABEL[summary.target_type as SubscriptionApi['target_type']] ?? summary.target_type
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-secondary">
                <Link
                    to={urls.subscription(summary.subscription)}
                    className="truncate"
                    data-attr="subscription-summary-subscription-link"
                >
                    {summary.subscription_title || 'Untitled subscription'}
                </Link>
                <span>·</span>
                <span>{channel}</span>
                <span>·</span>
                {summary.period_start ? (
                    <span>
                        Changes from <TZLabel time={summary.period_start} timestampStyle="absolute" /> to{' '}
                        <TZLabel time={summary.created_at} timestampStyle="absolute" />
                    </span>
                ) : (
                    <span>
                        Sent <TZLabel time={summary.created_at} timestampStyle="absolute" />
                    </span>
                )}
            </div>
            <div className="whitespace-pre-wrap text-sm">{summary.change_summary}</div>
        </div>
    )
}
