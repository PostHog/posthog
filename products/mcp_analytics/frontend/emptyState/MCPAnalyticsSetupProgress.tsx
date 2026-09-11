import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { installationProgressLogic } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { InstallationProgressView } from 'scenes/onboarding/shared/wizard-sync/InstallationProgressView'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

export function MCPAnalyticsSetupProgress({ mode }: { mode: ProductEmptyStateMode }): JSX.Element | null {
    const { installationProgress, latestSession } = useValues(
        installationProgressLogic({ mode: 'local', workflowId: 'mcp-analytics' })
    )
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))
    const sessionId = latestSession?.session_id
    const { isCurrent, phase } = installationProgress
    const { currentTeamId } = useValues(teamLogic)
    const matchesProject = latestSession?.team_id === currentTeamId

    useEffect(() => {
        if (isCurrent && matchesProject && sessionId) {
            reportSetupInteraction('wizard session observed', mode, null, false, { session_id: sessionId, phase })
        }
    }, [isCurrent, matchesProject, sessionId, phase, mode, reportSetupInteraction])

    return isCurrent && matchesProject ? (
        <InstallationProgressView
            mode="local"
            workflowId="mcp-analytics"
            docsUrl="https://posthog.com/docs/mcp-analytics/installation"
            continueHint="After setup, call an existing tool from your server to verify that its event arrives here."
        />
    ) : null
}
