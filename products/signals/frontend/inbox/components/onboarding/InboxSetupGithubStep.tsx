import { useValues } from 'kea'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { GuidedWizardSection } from 'lib/components/GuidedWizard/GuidedWizardSection'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { IntegrationAccessRequest } from 'scenes/integrations/components/IntegrationAccessRequest'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { InboxGithubAccessExplanation } from './InboxGithubAccessExplanation'
import { InboxSetupGithubConnect } from './InboxSetupGithubConnect'
import { InboxSetupGithubSkipDialog } from './InboxSetupGithubSkipDialog'
import { InboxSetupImplementation } from './InboxSetupImplementation'

export function InboxSetupGithubStep(): JSX.Element {
    const { hasGithubIntegration, githubIsOptional, activatesWithoutGithub } = useValues(inboxSetupLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })
    return (
        <>
            <GuidedWizardSection
                title={hasGithubIntegration ? 'GitHub is connected' : 'Connect GitHub for code context'}
                badge={githubIsOptional ? <LemonTag type="success">Recommended</LemonTag> : undefined}
                description="Self-driving uses your code to explain what's happening in your product and suggest what to do next."
            >
                {!hasGithubIntegration && restrictionReason ? (
                    <IntegrationAccessRequest kind="github" name="GitHub" />
                ) : (
                    <InboxSetupGithubConnect connectDescription="Choose which repositories PostHog can access when you connect GitHub." />
                )}
            </GuidedWizardSection>
            {!hasGithubIntegration && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 empty:hidden">
                    <InboxGithubAccessExplanation />
                </div>
            )}
            {featureFlags[FEATURE_FLAGS.SELF_DRIVING_UBP] && <InboxSetupImplementation />}
            {githubIsOptional && (
                <LemonBanner type="warning">
                    <span>
                        {activatesWithoutGithub
                            ? "Without GitHub, reports use your product data only. Agents can't trace problems to your code or open pull requests. You can connect GitHub later."
                            : 'Automatic implementation opens pull requests, so it needs GitHub. Connect GitHub to activate, or turn it off to activate without GitHub.'}
                    </span>
                </LemonBanner>
            )}
            <InboxSetupGithubSkipDialog canConnectGithub={!restrictionReason} />
        </>
    )
}
