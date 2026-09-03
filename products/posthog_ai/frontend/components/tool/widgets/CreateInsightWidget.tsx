import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import { extractInsightDashboardRevealTarget, extractVisualizationArtifact } from './extractors'
import { VisualizationWidget, getArtifactOpenTarget } from './VisualizationWidget'

/**
 * Renders insight create / update / read tool calls through `VisualizationWidget`. Until the
 * artifact lands (pending / in-progress / malformed output) we fall back to the generic card so
 * the call still renders something.
 */
export function CreateInsightWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const artifact = message.status === 'completed' ? extractVisualizationArtifact(message) : null

    if (!artifact) {
        return <GenericMcpToolRenderer {...props} />
    }

    const target = getArtifactOpenTarget(artifact.envelope, artifact.content)
    const revealTarget = extractInsightDashboardRevealTarget(message)
    const extraActions = revealTarget ? (
        <LemonButton
            to={urls.dashboard(revealTarget.dashboardId, revealTarget.insightShortId)}
            size="xsmall"
            data-attr="posthog-ai-show-insight-on-dashboard"
        >
            Show on dashboard
        </LemonButton>
    ) : null

    return (
        <DataToolRow {...props}>
            <VisualizationWidget
                content={artifact.content}
                openUrl={target.url}
                openTooltip={target.tooltip}
                extraActions={extraActions}
            />
        </DataToolRow>
    )
}
