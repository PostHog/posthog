import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { workflowsSendingLimitsLogic } from './workflowsSendingLimitsLogic'

export function SendingLimitsBanner(): JSX.Element | null {
    const { sendingLimits } = useValues(workflowsSendingLimitsLogic)

    if (!sendingLimits) {
        return null
    }

    const manageBilling = { children: 'Manage billing', to: urls.organizationBilling([ProductKey.WORKFLOWS]) }

    // LemonBanner drops unknown props, so each data-attr sits on a wrapper.
    return (
        <>
            {sendingLimits.email_quota_limited && (
                <div data-attr="workflows-email-quota-limited-banner">
                    <LemonBanner type="error" action={manageBilling}>
                        Your organization reached its usage limit for workflow emails. Workflow and broadcast emails are
                        not sent until the billing period resets or you raise the limit. Other workflow steps still run.
                    </LemonBanner>
                </div>
            )}
            {sendingLimits.destination_quota_limited && (
                <div data-attr="workflows-destination-quota-limited-banner">
                    <LemonBanner type="error" action={manageBilling}>
                        Your organization reached its usage limit for workflow destinations. Destination and push steps
                        are skipped until the billing period resets or you raise the limit. Other workflow steps still
                        run.
                    </LemonBanner>
                </div>
            )}
            {sendingLimits.email_daily_cap_reached && (
                <div data-attr="workflows-email-daily-cap-banner">
                    <LemonBanner
                        type="warning"
                        action={{ children: 'View sending allowance', to: urls.workflows('reputation') }}
                    >
                        This project reached its daily email sending limit{dailyCapSuffix(sendingLimits.emails_per_day)}
                        . Emails are not dropped. They are sent as the limit frees up, and the limit rises as your
                        workflows build a clean sending history.
                    </LemonBanner>
                </div>
            )}
        </>
    )
}

function dailyCapSuffix(emailsPerDay: number | null): string {
    return emailsPerDay ? ` of ${humanFriendlyNumber(emailsPerDay)} emails` : ''
}
