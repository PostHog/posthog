import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
    const { canEditNotebook, isShared, hasDataframeConsumers } = useValues(notebookLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const enabled =
        !!(
            featureFlags[FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS] || featureFlags[FEATURE_FLAGS.NOTEBOOK_GENERATED_WIDGETS]
        ) &&
        canEditNotebook &&
        !isShared &&
        // A prepared dataframe keeps its footer, so it can still be refreshed.
        (hasDataframeConsumers || !!attributes.runId)
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
