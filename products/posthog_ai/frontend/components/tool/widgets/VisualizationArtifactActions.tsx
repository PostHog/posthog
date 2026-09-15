import { useValues } from 'kea'
import React, { useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { VisualizationArtifactContent } from '~/queries/schema/schema-assistant-messages'

import { artifactActionsLogic } from '../../../logics/artifactActionsLogic'
import type { VisualizationArtifactActionPayload } from '../../../types/artifactActionTypes'
import { visualizationTypeToQuery } from '../../../utils/visualizationQuery'

export interface VisualizationArtifactActionsProps {
    content: VisualizationArtifactContent
    /** Resolved tool name that produced the card, e.g. `query-trends`. */
    toolName: string
    toolCallId: string
    /** Short id of the saved insight behind the card, when the artifact came from one. */
    insightShortId?: string
}

/**
 * Renders the host-registered actions for one visualization card. Returns null when no host is on
 * screen, which is the usual case, so the row stays as it was.
 */
export const VisualizationArtifactActions = React.memo(function VisualizationArtifactActions({
    content,
    toolName,
    toolCallId,
    insightShortId,
}: VisualizationArtifactActionsProps): JSX.Element | null {
    const { visualizationActions } = useValues(artifactActionsLogic)

    const payload = useMemo<VisualizationArtifactActionPayload>(
        () => ({
            query: visualizationTypeToQuery(content),
            content,
            insightShortId,
            toolName,
            toolCallId,
        }),
        [content, insightShortId, toolName, toolCallId]
    )

    if (visualizationActions.length === 0) {
        return null
    }

    return (
        <>
            {visualizationActions.map((action) => (
                <LemonButton
                    key={action.id}
                    size="xsmall"
                    icon={action.icon}
                    onClick={() => action.onSelect(payload)}
                    data-attr={`visualization-artifact-action-${action.id}`}
                >
                    {action.label}
                </LemonButton>
            ))}
        </>
    )
})
