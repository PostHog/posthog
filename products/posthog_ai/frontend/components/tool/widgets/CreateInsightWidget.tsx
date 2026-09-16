import { ArtifactSource } from '~/queries/schema/schema-assistant-messages'

import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import { extractVisualizationArtifact } from './extractors'
import { VisualizationArtifactActions } from './VisualizationArtifactActions'
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
    const insightShortId =
        artifact.envelope.source === ArtifactSource.Insight ? artifact.envelope.artifact_id : undefined

    return (
        <DataToolRow {...props}>
            <VisualizationWidget
                content={artifact.content}
                openUrl={target.url}
                openTooltip={target.tooltip}
                extraActions={
                    <VisualizationArtifactActions
                        content={artifact.content}
                        toolName={message.resolvedKey}
                        toolCallId={message.id}
                        insightShortId={insightShortId}
                    />
                }
            />
        </DataToolRow>
    )
}
