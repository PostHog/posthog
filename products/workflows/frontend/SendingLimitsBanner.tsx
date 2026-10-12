import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { workflowsSendingLimitsLogic } from './workflowsSendingLimitsLogic'

const WORKFLOW_EMAILS_BILLING_TYPE = 'workflows_emails' as ProductKey
const WORKFLOW_DESTINATIONS_BILLING_TYPE = 'workflows_destinations' as ProductKey

function manageBillingFor(billingType: ProductKey): { children: string; to: string } {
    return { children: 'Manage billing', to: urls.organizationBilling([billingType]) }
}

export function SendingLimitsBanner(): JSX.Element | null {
    const { sendingLimits } = useValues(workflowsSendingLimitsLogic)

    if (!sendingLimits) {
        return null
    }

    // LemonBanner drops unknown props, so each data-attr sits on a wrapper.
    return (
        <>
            {sendingLimits.email_quota_limited && (
                <div data-attr="workflows-email-quota-limited-banner">
                    <LemonBanner type="error" action={manageBillingFor(WORKFLOW_EMAILS_BILLING_TYPE)}>
                        Your organization reached its usage limit for workflow emails. Workflows and broadcasts that
                        send email do not run until the billing period resets or you raise the limit.
                    </LemonBanner>
                </div>
            )}
            {sendingLimits.destination_quota_limited && (
                <div data-attr="workflows-destination-quota-limited-banner">
                    <LemonBanner type="error" action={manageBillingFor(WORKFLOW_DESTINATIONS_BILLING_TYPE)}>
                        Your organization reached its usage limit for workflow destinations. Workflows with a
                        destination or push step do not run until the billing period resets or you raise the limit.
                    </LemonBanner>
                </div>
            )}
        </>
    )
}
