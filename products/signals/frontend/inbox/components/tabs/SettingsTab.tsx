import { useMountedLogic, useValues } from 'kea'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { urls } from 'scenes/urls'

import { inboxUsageLogic } from '../../logics/inboxUsageLogic'
import { AgentSteeringSection } from '../config/AgentSteeringSection'
import { RepoRoutingRules } from '../config/RepoRoutingRules'
import { SelfDrivingSection } from '../config/SelfDrivingSection'
import { SlackNotificationsSection } from '../config/SlackNotificationsSection'
import { InboxUsageWidget } from '../shell/InboxUsageWidget'
import { InstallationSetupSection } from '../shell/InstallationSetupSection'
import { SettingsSection } from './SettingsSection'

export function SettingsTab(): JSX.Element {
    useMountedLogic(integrationsLogic)
    // The usage widget renders nothing without the billing product, so the section title
    // must hide with it rather than sit over an empty area.
    const { product: inboxUsageProduct, isLoading: inboxUsageLoading } = useValues(inboxUsageLogic)

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-6">
            <InstallationSetupSection />
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
            {(inboxUsageProduct != null || inboxUsageLoading) && (
                <SettingsSection title="Usage" description="Pull requests agents opened this billing period.">
                    <InboxUsageWidget />
                </SettingsSection>
            )}
        </div>
    )
}
