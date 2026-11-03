import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { AIAccessRequest } from 'scenes/settings/organization/AIAccessRequest'
import { openAIConsentLegalDialog } from 'scenes/settings/organization/aiConsentCopy'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'

import { slackAppWorkspaceSetupLogic } from '../slackAppWorkspaceSetupLogic'

export function AIConsentStep(): JSX.Element {
    const { isAdminOrOwner, currentOrganization } = useValues(organizationLogic)
    const { dataProcessingApprovalDisabledReason } = useValues(aiConsentLogic)
    const { setPendingApprovalRedirect } = useActions(aiConsentLogic)
    const { acceptDataProcessing } = useAsyncActions(aiConsentLogic)
    const { completeStep, skipStep } = useActions(slackAppWorkspaceSetupLogic)
    const { location } = useValues(router)
    const [approving, setApproving] = useState(false)

    const approve = async (): Promise<void> => {
        if (currentOrganization) {
            // Approving can need a fresh login, which reloads the page. The pending redirect brings
            // the person back to this setup, and the step is then done.
            setPendingApprovalRedirect({
                url: location.pathname,
                organizationId: currentOrganization.id,
                setAt: Date.now(),
            })
        }
        setApproving(true)
        try {
            await acceptDataProcessing()
            completeStep('ai_consent')
        } finally {
            setApproving(false)
        }
    }

    return (
        <>
            <div className="flex flex-col items-center gap-1 text-center">
                <h1 className="text-2xl font-bold m-0">Allow AI data processing</h1>
                <p className="text-secondary m-0">
                    PostHog in Slack uses AI models to answer from your PostHog data. An organization admin must allow
                    this once for {currentOrganization?.name ?? 'your organization'}. Until then, PostHog can't answer
                    in Slack.
                </p>
            </div>

            {isAdminOrOwner ? (
                <LemonButton
                    type="primary"
                    data-attr="slack-app-workspace-setup-allow-ai"
                    loading={approving}
                    disabledReason={dataProcessingApprovalDisabledReason}
                    onClick={() => openAIConsentLegalDialog({ onConfirm: approve })}
                >
                    Allow AI data processing
                </LemonButton>
            ) : (
                <div className="flex flex-col items-center gap-2 text-center">
                    <p className="text-secondary m-0">Only an organization admin can allow this. Ask one of them.</p>
                    <AIAccessRequest size="small" />
                </div>
            )}

            <LemonButton type="tertiary" size="small" onClick={() => skipStep('ai_consent')}>
                Skip for now
            </LemonButton>
        </>
    )
}
