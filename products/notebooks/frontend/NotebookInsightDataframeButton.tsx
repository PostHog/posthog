import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { useRequiredNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'

import type { InsightLogicProps } from '~/types'

import { notebookInsightDataframeLogic } from './notebookInsightDataframeLogic'

export function NotebookInsightDataframeButton({
    insightProps,
}: {
    insightProps: InsightLogicProps
}): JSX.Element | null {
    const { notebookLogic } = useValues(useRequiredNotebookNode())
    const { canEditNotebook, isShared } = useValues(notebookLogic)
    const logic = notebookInsightDataframeLogic({ notebookLogic, insightProps })
    const { createDataframe } = useActions(logic)
    const { isCreatingDataframe } = useValues(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { insightDataLoading } = useValues(insightDataLogic(insightProps))

    if (isShared || !canEditNotebook || !featureFlags[FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS]) {
        return null
    }

    return (
        <LemonButton
            size="small"
            className="self-start mb-2"
            onClick={createDataframe}
            loading={isCreatingDataframe || insightDataLoading}
            tooltip="Add a SQL cell with this insight's query. Run the cell to use its dataframe in SQL, Python, or widgets."
            data-attr="notebook-insight-create-dataframe"
        >
            Use as dataframe
        </LemonButton>
    )
}
