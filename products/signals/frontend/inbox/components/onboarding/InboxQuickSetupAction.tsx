import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { IntegrationAccessRequest } from 'scenes/integrations/components/IntegrationAccessRequest'
import { urls } from 'scenes/urls'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { useScoutCreateDisabledReason } from '../config/scouts/ScoutCreateModalHost'

export function InboxQuickSetupAction(): JSX.Element {
    const { connectGithub, activateQuickSetup, resumeQuickSetup, retry } = useActions(inboxSetupLogic)
    const {
        hasGithubIntegration,
        isGithubOptionalSetup,
        quickActivationPending,
        saving,
        error,
        shouldResumeQuickSetup,
    } = useValues(inboxSetupLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const scoutDisabledReason = useScoutCreateDisabledReason()
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    useEffect(() => {
        if (!restrictionReason && !scoutDisabledReason) {
            resumeQuickSetup()
        }
    }, [shouldResumeQuickSetup, resumeQuickSetup, restrictionReason, scoutDisabledReason])

    const busy = saving || quickActivationPending

    return (
        <div className="flex w-full flex-col items-start gap-3">
            {hasGithubIntegration || isGithubOptionalSetup ? (
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={() => activateQuickSetup()}
                    loading={busy}
                    disabledReason={restrictionReason || scoutDisabledReason}
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
                    authorizing={saving || (integrationsLoading && integrations === null)}
                    connectText="Connect GitHub"
                    emphasizeConnect
                    showPersonalConnectionHelp={false}
                    showManageButton={false}
                    integrationSuffix={<></>}
                    connectDescription=""
                />
            )}
            {error && (
                <LemonBanner type="error" className="w-full">
                    <span>{error}</span>
                    <LemonButton
                        size="small"
                        onClick={retry}
                        loading={busy}
                        disabledReason={restrictionReason || scoutDisabledReason}
                    >
                        Retry
                    </LemonButton>
                </LemonBanner>
            )}
        </div>
    )
}
