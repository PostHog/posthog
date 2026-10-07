import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { workflowsEmailSuspensionLogic } from './workflowsEmailSuspensionLogic'
import { workflowsSendingLimitsLogic } from './workflowsSendingLimitsLogic'

const WORKFLOW_EMAILS_BILLING_TYPE = 'workflows_emails' as ProductKey
const WORKFLOW_DESTINATIONS_BILLING_TYPE = 'workflows_destinations' as ProductKey

function manageBillingFor(billingType: ProductKey): { children: string; to: string } {
    return { children: 'Manage billing', to: urls.organizationBilling([billingType]) }
}

export function SendingLimitsBanner({
    sendingAllowanceUrl,
}: {
    /** Where the sending allowance lives on this surface. Leave it out where the allowance is already on screen. */
    sendingAllowanceUrl?: string
}): JSX.Element | null {
    const { sendingLimits } = useValues(workflowsSendingLimitsLogic)
    const { emailSendingSuspended, suspensionStatusLoading } = useValues(workflowsEmailSuspensionLogic)

    if (!sendingLimits) {
        return null
    }

    // The daily cap promises that held emails go out later, which is false while another block stops every email.
    const emailsWaitForAllowance =
        sendingLimits.email_daily_cap_reached &&
        !sendingLimits.email_quota_limited &&
        !suspensionStatusLoading &&
        !emailSendingSuspended

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
            {emailsWaitForAllowance && (
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
