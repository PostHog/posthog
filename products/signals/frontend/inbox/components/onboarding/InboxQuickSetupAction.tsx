import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { IntegrationAccessRequest } from 'scenes/integrations/components/IntegrationAccessRequest'
import { urls } from 'scenes/urls'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'

export function InboxQuickSetupAction(): JSX.Element {
    const { startSetup, connectGithub, activateQuickSetup, resumeQuickSetup } = useActions(inboxSetupLogic)
    const { hasGithubIntegration, integrationsLoading, quickSetupReady, saving, error, shouldResumeQuickSetup } =
        useValues(inboxSetupLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    useEffect(() => startSetup(), [startSetup])
    useEffect(() => resumeQuickSetup(), [shouldResumeQuickSetup, resumeQuickSetup])

    return (
        <div className="flex w-full flex-col items-start gap-3">
            {integrationsLoading ? (
                <Spinner />
            ) : hasGithubIntegration ? (
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={activateQuickSetup}
                    loading={saving}
                    disabledReason={
                        restrictionReason ||
                        (!quickSetupReady ? 'Loading your available sources and general scout' : undefined)
                    }
                    data-attr="inbox-quick-activate"
                >
                    Activate Self-Driving
                </LemonButton>
            ) : restrictionReason ? (
                <IntegrationAccessRequest kind="github" name="GitHub" />
            ) : (
                <GithubIntegration
                    next={combineUrl(urls.inbox(), { onboarding_step: 'quick' }).url}
                    connectSurface="inbox_welcome"
                    onAuthorize={connectGithub}
                    authorizing={saving}
                    connectText="Connect GitHub"
                    emphasizeConnect
                    showPersonalConnectionHelp={false}
                    showManageButton={false}
                    integrationSuffix={<></>}
                    connectDescription="Choose which repositories PostHog can use to investigate your product."
                />
            )}
            <p className="m-0 text-sm text-secondary">
                We’ll enable your available sources and a general scout, then take you to your Inbox. You can adjust
                them there.
            </p>
            {error && (
                <LemonBanner type="error">
                    {error}
                    <LemonButton
                        size="small"
                        onClick={quickSetupReady ? activateQuickSetup : startSetup}
                        loading={saving}
                    >
                        Retry
                    </LemonButton>
                </LemonBanner>
            )}
        </div>
    )
}
