import { useActions } from 'kea'
import { useState } from 'react'

import { IconLetter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { mcpRecurringReportsLogic } from '../notifications/mcpRecurringReportsLogic'
import type { ActionableWeeklyReportOffer } from '../notifications/weeklyReportOffer'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

// pinned: autocapture dashboards and Playwright selectors depend on it
const DATA_ATTR = 'mcp-analytics-activity-next-step-weekly-report'

export function WeeklyReportActions({ offer }: { offer: ActionableWeeklyReportOffer }): JSX.Element {
    const { nextStepClicked } = useActions(mcpEarlyDataLogic)
    const { createWeeklyReport } = useActions(mcpRecurringReportsLogic)
    const [consentOpen, setConsentOpen] = useState(false)

    if (offer.state === 'created') {
        return (
            <LemonButton
                type="secondary"
                size="small"
                to={urls.subscription(offer.report.id)}
                onClick={() => nextStepClicked('weekly-report', 'manage-report')}
                data-attr={`${DATA_ATTR}-manage`}
            >
                Manage
            </LemonButton>
        )
    }

    const createButton = (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconLetter />}
            loading={offer.state === 'creating'}
            onClick={() => {
                if (offer.state === 'needs-ai-consent') {
                    nextStepClicked('weekly-report', 'open-consent')
                    setConsentOpen(true)
                } else {
                    nextStepClicked('weekly-report', 'create-report')
                    createWeeklyReport()
                }
            }}
            data-attr={DATA_ATTR}
        >
            {offer.state === 'failed' ? 'Try again' : 'Email me weekly'}
        </LemonButton>
    )

    return (
        <>
            {offer.state === 'needs-ai-consent' ? (
                <AIConsentPopoverWrapper
                    hidden={!consentOpen}
                    ignoreDismissal
                    pendingRedirectUrl={urls.mcpAnalyticsActivity()}
                    onDismiss={() => setConsentOpen(false)}
                    onApprove={() => {
                        setConsentOpen(false)
                        createWeeklyReport()
                    }}
                >
                    {createButton}
                </AIConsentPopoverWrapper>
            ) : (
                createButton
            )}
            <LemonButton
                type="tertiary"
                size="small"
                to={urls.mcpAnalyticsNotifications()}
                onClick={() => nextStepClicked('weekly-report', 'more-options')}
                data-attr={`${DATA_ATTR}-options`}
            >
                Other destinations
            </LemonButton>
        </>
    )
}
