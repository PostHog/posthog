import { useValues } from 'kea'

import { useRequiredNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'

import type { InsightLogicProps } from '~/types'

import { NotebookInsightDataframeFooter } from './NotebookInsightDataframeFooter'
import { InsightDataframeAttributes } from './notebookInsightDataframeLogic'

export function NotebookInsightDataframe({
    insightProps,
    attributes,
    updateAttributes,
}: {
    insightProps: InsightLogicProps
    attributes: InsightDataframeAttributes
    updateAttributes: (attributes: Partial<InsightDataframeAttributes>) => void
}): JSX.Element | null {
    const { notebookLogic, nodeId } = useValues(useRequiredNotebookNode())
    const { canEditNotebook, isShared } = useValues(notebookLogic)
    const enabled = canEditNotebook && !isShared
    if (!enabled) {
        return null
    }
    return (
        <NotebookInsightDataframeFooter
            notebookLogic={notebookLogic}
            nodeId={nodeId}
            insightProps={insightProps}
            attributes={attributes}
            updateAttributes={updateAttributes}
            enabled
        />
    )
}
