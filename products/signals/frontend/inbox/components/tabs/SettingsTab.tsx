import { useMountedLogic, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { urls } from 'scenes/urls'

import { inboxUsageLogic } from '../../logics/inboxUsageLogic'
import { AgentSteeringSection } from '../config/AgentSteeringSection'
import { RepoRoutingRules } from '../config/RepoRoutingRules'
import { SelfDrivingSection } from '../config/SelfDrivingSection'
import { SlackNotificationsSection } from '../config/SlackNotificationsSection'
import { InboxUsageWidget } from '../shell/InboxUsageWidget'
import { UsageOverview } from '../spend/UsageOverview'
import { SettingsSection } from './SettingsSection'

export function SettingsTab(): JSX.Element {
    const usageEnabled = useFeatureFlag('SELF_DRIVING_USAGE_DISPLAY')
    useMountedLogic(integrationsLogic)
    const { product: inboxUsageProduct, spendProduct, isLoading: inboxUsageLoading } = useValues(inboxUsageLogic)
    const showBillingUsage = inboxUsageProduct != null || spendProduct != null || inboxUsageLoading

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-6">
            <SettingsSection
                title="Autonomy"
                description="How much agents do on their own: opening pull requests, and how many reports arrive each day."
            >
                <SelfDrivingSection />
            </SettingsSection>
            <AgentSteeringSection />
            <SettingsSection
                title="Code access"
                description="Connect GitHub so agents can read repositories and open pull requests."
            >
                {/* The OAuth round trip returns to `next`; land back on this tab so the result is in view. */}
                <GithubIntegration next={urls.inbox('settings')} connectSurface="signals_agent_setup" />
                <RepoRoutingRules />
            </SettingsSection>
            <SettingsSection
                title="Notifications"
                description="Post reports to a Slack channel, and get pinged when you're a suggested reviewer."
            >
                <SlackNotificationsSection />
            </SettingsSection>
            {(showBillingUsage || usageEnabled) && (
                <SettingsSection
                    title="Usage"
                    description={
                        showBillingUsage
                            ? spendProduct
                                ? 'Recorded billable usage this billing period.'
                                : 'Pull requests agents opened this billing period.'
                            : undefined
                    }
                >
                    {showBillingUsage && <InboxUsageWidget />}
                    {usageEnabled && (
                        <div className={showBillingUsage ? 'border-t border-primary pt-3' : undefined}>
                            <div className="mb-3 flex flex-col gap-0.5">
                                <h4 className="m-0 text-sm font-semibold text-default">Usage breakdown</h4>
                                <p className="m-0 max-w-2xl text-xs leading-snug text-secondary">
                                    Recorded usage for scout runs started and signals received in the last 30 days.
                                </p>
                            </div>
                            <UsageOverview />
                        </div>
                    )}
                </SettingsSection>
            )}
        </div>
    )
}
