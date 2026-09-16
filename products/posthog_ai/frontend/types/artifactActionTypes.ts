import type { ReactElement } from 'react'

import { VisualizationArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { QuerySchema } from '~/queries/schema/schema-general'

/**
 * What a visualization card hands an action when the user selects it. `query` is the query the card
 * itself renders, so a host does not have to repeat the artifact-to-query mapping.
 */
export interface VisualizationArtifactActionPayload {
    /** Null when the artifact holds no query the surface can render. */
    query: QuerySchema | null
    content: VisualizationArtifactContent
    /** Short id of the saved insight behind the card. Absent for an ephemeral query result. */
    insightShortId?: string
    /** Resolved tool name that produced the card, e.g. `query-trends`. */
    toolName: string
    toolCallId: string
}

/** An action a host contributes to every visualization card in the thread. */
export interface VisualizationArtifactAction {
    /** Stable id: the React key, and the dedupe key across providers. */
    id: string
    label: string
    icon?: ReactElement
    onSelect: (payload: VisualizationArtifactActionPayload) => void
}
