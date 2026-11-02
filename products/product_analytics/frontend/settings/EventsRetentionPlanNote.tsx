import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { OrganizationEventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'
import { LONGEST_PLAN_RETENTION_MONTHS } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

import { retentionPeriodLabel } from './retentionPeriodLabel'

export type EventsRetentionPlan = Pick<
    OrganizationEventsRetentionApi,
    'plan_retention_months' | 'default_retention_months' | 'default_is_grandfathered'
>

function planSummary(plan: EventsRetentionPlan): string {
    const longest = retentionPeriodLabel(plan.plan_retention_months)
    const byDefault = retentionPeriodLabel(plan.default_retention_months)
    if (plan.default_is_grandfathered) {
        return `Your plan allows up to ${longest} for custom events retention policies. It predates the current default, so its default retention period stays at ${byDefault}.`
    }
    if (plan.default_retention_months < plan.plan_retention_months) {
        return `Your plan allows up to ${longest} for custom events retention policies. The default retention period for this plan is ${byDefault}.`
    }
    return `Your plan has ${longest} of events data retention.`
}

export function EventsRetentionPlanNote({ plan }: { plan: EventsRetentionPlan }): JSX.Element {
    return (
        <p
            className="max-w-160 mb-4 rounded border bg-surface-primary px-3 py-2 text-secondary"
            data-attr="events-retention-plan-note"
        >
            <span>{planSummary(plan)}</span>
            {plan.plan_retention_months < LONGEST_PLAN_RETENTION_MONTHS && (
                <>
                    {' '}
                    Need longer data retention? Head over to our{' '}
                    <Link to={urls.organizationBilling()}>billing page</Link> to upgrade.
                </>
            )}
        </p>
    )
}
