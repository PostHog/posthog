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
    const { startSetup, connectGithub, activateQuickSetup, resumeQuickSetup, retry } = useActions(inboxSetupLogic)
    const { hasGithubIntegration, quickSetupReady, saving, error, shouldResumeQuickSetup, failedOperation } =
        useValues(inboxSetupLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const scoutDisabledReason = useScoutCreateDisabledReason()
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    useEffect(() => startSetup(), [startSetup])
    useEffect(() => {
        if (!restrictionReason && !scoutDisabledReason) {
            resumeQuickSetup()
        }
    }, [shouldResumeQuickSetup, resumeQuickSetup, restrictionReason, scoutDisabledReason])

    return (
        <div className="flex w-full flex-col items-start gap-3">
            {hasGithubIntegration ? (
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={() => activateQuickSetup()}
                    loading={saving}
                    disabledReason={
                        restrictionReason ||
                        scoutDisabledReason ||
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
                <LemonBanner type="error">
                    {error}
                    <LemonButton
                        size="small"
                        onClick={
                            failedOperation === 'scouts' || failedOperation === 'sources'
                                ? retry
                                : quickSetupReady
                                  ? () => activateQuickSetup('retry')
                                  : startSetup
                        }
                        loading={saving}
                        disabledReason={restrictionReason || scoutDisabledReason}
                    >
                        Retry
                    </LemonButton>
                </LemonBanner>
            )}
        </div>
    )
}
