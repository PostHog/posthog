import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import {
    extractInsightDashboardRevealTarget,
    extractVisualizationArtifact,
    insightRequestIncludesDashboardTarget,
} from './extractors'
import { VisualizationWidget, getArtifactOpenTarget } from './VisualizationWidget'

/**
 * Renders insight create / update / read tool calls through `VisualizationWidget`. Until the
 * artifact lands (pending / in-progress / malformed output) we fall back to the generic card so
 * the call still renders something.
 */
export function CreateInsightWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const artifact = message.status === 'completed' ? extractVisualizationArtifact(message) : null
    const dashboardTarget = extractInsightDashboardRevealTarget(message)

    if (!artifact || (insightRequestIncludesDashboardTarget(message) && !dashboardTarget)) {
        return <GenericMcpToolRenderer {...props} />
    }

    const target = getArtifactOpenTarget(artifact.envelope, artifact.content)
    const dashboardAction = dashboardTarget ? (
        <LemonButton
            to={urls.dashboard(dashboardTarget.dashboardId, undefined, dashboardTarget.tileId)}
            size="xsmall"
            onClick={() =>
                posthog.capture('posthog ai dashboard reveal clicked', {
                    source: 'tool_card',
                    target_kind: 'tile',
                })
            }
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
                extraActions={dashboardAction}
            />
        </DataToolRow>
    )
}
