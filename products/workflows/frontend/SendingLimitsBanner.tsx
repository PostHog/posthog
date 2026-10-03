import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { workflowsSendingLimitsLogic } from './workflowsSendingLimitsLogic'

// The billing page scrolls to the product whose billing type matches, and Workflows bills as `workflows_emails`.
const WORKFLOWS_BILLING_PRODUCT = 'workflows_emails' as ProductKey

export function SendingLimitsBanner({
    sendingAllowanceUrl,
}: {
    /** Where the sending allowance lives on this surface. Leave it out where the allowance is already on screen. */
    sendingAllowanceUrl?: string
}): JSX.Element | null {
    const { sendingLimits } = useValues(workflowsSendingLimitsLogic)

    if (!sendingLimits) {
        return null
    }

    const manageBilling = { children: 'Manage billing', to: urls.organizationBilling([WORKFLOWS_BILLING_PRODUCT]) }

    // LemonBanner drops unknown props, so each data-attr sits on a wrapper.
    return (
        <>
            {sendingLimits.email_quota_limited && (
                <div data-attr="workflows-email-quota-limited-banner">
                    <LemonBanner type="error" action={manageBilling}>
                        Your organization reached its usage limit for workflow emails. Workflows and broadcasts that
                        send email do not run until the billing period resets or you raise the limit.
                    </LemonBanner>
                </div>
            )}
            {sendingLimits.destination_quota_limited && (
                <div data-attr="workflows-destination-quota-limited-banner">
                    <LemonBanner type="error" action={manageBilling}>
                        Your organization reached its usage limit for workflow destinations. Workflows with a
                        destination or push step do not run until the billing period resets or you raise the limit.
                    </LemonBanner>
                </div>
            )}
            {sendingLimits.email_daily_cap_reached && !sendingLimits.email_quota_limited && (
                <div data-attr="workflows-email-daily-cap-banner">
                    <LemonBanner
                        type="warning"
                        action={
                            sendingAllowanceUrl
                                ? { children: 'View sending allowance', to: sendingAllowanceUrl }
                                : undefined
                        }
                    >
                        This project used its daily sending allowance
                        {dailyAllowanceSuffix(sendingLimits.emails_per_day)} in the last 24 hours. Emails are not
                        dropped. They are sent as the allowance frees up, and it grows as your workflows build a clean
                        sending history.
                    </LemonBanner>
                </div>
            )}
        </>
    )
}

function dailyAllowanceSuffix(emailsPerDay: number | null): string {
    return emailsPerDay ? ` of ${humanFriendlyNumber(emailsPerDay)} emails` : ''
}
