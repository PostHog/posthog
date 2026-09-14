import { useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { NotebookCellOutputNameFooter } from 'scenes/notebooks/Nodes/components/NotebookCellOutputNameFooter'
import { useRequiredNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { returnVariableValidationError } from 'scenes/notebooks/Nodes/NotebookNodeSQLV2'

import type { InsightLogicProps } from '~/types'

import { InsightDataframeAttributes, notebookInsightDataframeLogic } from './notebookInsightDataframeLogic'

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
    const { featureFlags } = useValues(featureFlagLogic)
    const enabled = !!featureFlags[FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS] && canEditNotebook && !isShared
    const logic = notebookInsightDataframeLogic({
        notebookLogic,
        nodeId,
        insightProps,
        attributes,
        updateAttributes,
        enabled,
    })
    const { returnVariable, isPreparing, error } = useValues(logic)
    const { setReturnVariable, retry } = useActions(logic)

    if (!enabled) {
        return null
    }

    return (
        <NotebookCellOutputNameFooter returnVariable={returnVariable} onChange={setReturnVariable}>
            {returnVariableValidationError(returnVariable) ? (
                <span className="text-danger">{returnVariableValidationError(returnVariable)}</span>
            ) : isPreparing ? (
                <span className="flex items-center gap-1">
                    <Spinner className="text-sm" /> Preparing dataframe
                </span>
            ) : error ? (
                <LemonButton size="xsmall" type="tertiary" onClick={retry} tooltip={error}>
                    Retry dataframe
                </LemonButton>
            ) : null}
        </NotebookCellOutputNameFooter>
    )
}
