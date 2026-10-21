import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconWrench } from '@posthog/icons'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Button } from 'lib/ui/quill'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { buildIssueFixPrompt } from '../../components/ExceptionCard/aiPrompts'
import { ConnectGitHubToFixModal } from './ConnectGitHubToFixModal'

export function IssueFixButton({ issueId }: { issueId: string }): JSX.Element {
    const { integrations, integrationsLoading, getIntegrationsByKind } = useValues(integrationsLogic)
    const [connectDialogOpen, setConnectDialogOpen] = useState(false)
    const githubConnected = getIntegrationsByKind(['github']).length > 0
    const connectUrl = api.integrations.authorizeUrl({ kind: 'github', next: urls.errorTrackingIssue(issueId) })

    const onFix = (): void => {
        if (integrations === null || integrationsLoading) {
            return
        }
        posthog.capture('error_tracking_fix_clicked', { issue_id: issueId, github_connected: githubConnected })
        if (!githubConnected) {
            setConnectDialogOpen(true)
            return
        }
        newInternalTab(urls.ai(undefined, buildIssueFixPrompt(issueId)))
        posthog.capture('error_tracking_fix_ai_opened', { issue_id: issueId })
    }

    return (
        <>
            <Button
                variant="primary"
                onClick={onFix}
                disabled={integrations === null || integrationsLoading}
                title={
                    integrations === null && !integrationsLoading
                        ? "Couldn't check GitHub. Refresh the page and try again."
                        : undefined
                }
                data-attr="error-tracking-fix"
            >
                <IconWrench />
                Fix
            </Button>
            <ConnectGitHubToFixModal
                open={connectDialogOpen}
                onOpenChange={setConnectDialogOpen}
                connectUrl={connectUrl}
                onConnect={() => posthog.capture('error_tracking_fix_connect_github_clicked', { issue_id: issueId })}
            />
        </>
    )
}
