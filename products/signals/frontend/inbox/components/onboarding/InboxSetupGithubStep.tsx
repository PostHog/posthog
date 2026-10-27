import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { GuidedWizardSection } from 'lib/components/GuidedWizard/GuidedWizardSection'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { IntegrationAccessRequest } from 'scenes/integrations/components/IntegrationAccessRequest'
import { urls } from 'scenes/urls'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { InboxSetupImplementation } from './InboxSetupImplementation'

export function InboxSetupGithubStep(): JSX.Element {
    const { hasGithubIntegration, saving } = useValues(inboxSetupLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { connectGithub } = useActions(inboxSetupLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })
    return (
        <>
            <GuidedWizardSection
                title={hasGithubIntegration ? 'GitHub is connected' : 'Connect GitHub for code context'}
                description="Self-Driving uses your code to explain what's happening in your product and suggest what to do next."
            >
                {!hasGithubIntegration && restrictionReason ? (
                    <IntegrationAccessRequest kind="github" name="GitHub" />
                ) : (
                    <GithubIntegration
                        next={combineUrl(urls.inbox(), { onboarding_step: 'github' }).url}
                        connectSurface="inbox_welcome"
                        onAuthorize={connectGithub}
                        authorizing={saving}
                        connectText="Connect GitHub"
                        emphasizeConnect
                        showPersonalConnectionHelp={false}
                        showManageButton={false}
                        integrationSuffix={<></>}
                        connectDescription="Choose which repositories PostHog can access when you connect GitHub."
                    />
                )}
            </GuidedWizardSection>
            {featureFlags[FEATURE_FLAGS.SELF_DRIVING_UBP] && <InboxSetupImplementation />}
        </>
    )
}
