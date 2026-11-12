import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { billingLogic } from 'lib/logic/billing/billingLogic'
import { retentionPeriodLabel } from 'lib/utils/retentionPeriodLabel'
import { urls } from 'scenes/urls'

import { BillingPlan } from '~/types'

import type { OrganizationEventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'
import { LONGEST_PLAN_RETENTION_MONTHS } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

export type EventsRetentionPlan = Pick<
    OrganizationEventsRetentionApi,
    'plan_retention_months' | 'default_retention_months' | 'default_is_grandfathered'
>

const BILLING_PLAN_NAMES: Record<BillingPlan, string> = {
    [BillingPlan.Free]: 'Free',
    [BillingPlan.Paid]: 'Pay-as-you-go',
    [BillingPlan.Teams]: 'Teams',
    [BillingPlan.Boost]: 'Boost',
    [BillingPlan.Scale]: 'Scale',
    [BillingPlan.Enterprise]: 'Enterprise',
}

function planSummary(plan: EventsRetentionPlan, billingPlan: BillingPlan | null): string {
    const yourPlan = billingPlan ? `You're on the ${BILLING_PLAN_NAMES[billingPlan]} plan, which` : 'Your plan'
    const longest = retentionPeriodLabel(plan.plan_retention_months)
    const byDefault = retentionPeriodLabel(plan.default_retention_months)
    if (plan.default_is_grandfathered || plan.default_retention_months < plan.plan_retention_months) {
        return `${yourPlan} allows up to ${longest} for custom events retention policies. The default retention period for this plan is ${byDefault}.`
    }
    return `${yourPlan} has ${longest} of events data retention.`
}

export function EventsRetentionPlanNote({ plan }: { plan: EventsRetentionPlan }): JSX.Element {
    const { billingPlan } = useValues(billingLogic)

    return (
        <p
            className="max-w-160 mb-4 rounded border bg-surface-primary px-3 py-2 text-secondary"
            data-attr="events-retention-plan-note"
        >
            <span>{planSummary(plan, billingPlan)}</span>
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
