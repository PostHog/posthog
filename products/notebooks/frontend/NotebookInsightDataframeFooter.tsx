import { useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { NotebookCellOutputNameFooter } from 'scenes/notebooks/Nodes/components/NotebookCellOutputNameFooter'
import { returnVariableValidationError } from 'scenes/notebooks/Nodes/NotebookNodeSQLV2'

import { notebookInsightDataframeLogic, NotebookInsightDataframeLogicProps } from './notebookInsightDataframeLogic'

export function NotebookInsightDataframeFooter(props: NotebookInsightDataframeLogicProps): JSX.Element {
    const logic = notebookInsightDataframeLogic(props)
    const { returnVariable, isPreparing, error, unsupported } = useValues(logic)
    const { setReturnVariable, retry } = useActions(logic)
    return (
        <NotebookCellOutputNameFooter returnVariable={returnVariable} onChange={setReturnVariable}>
            {returnVariableValidationError(returnVariable) ? (
                <span className="text-danger">{returnVariableValidationError(returnVariable)}</span>
            ) : isPreparing ? (
                <span className="flex items-center gap-1">
                    <Spinner className="text-sm" /> Preparing {returnVariable}
                </span>
            ) : error ? (
                <span className="flex flex-wrap items-center gap-1">
                    <span className={unsupported ? 'text-secondary' : 'text-danger'}>{error}</span>
                    {!unsupported && (
                        <LemonButton size="xsmall" type="tertiary" onClick={retry}>
                            Try again
                        </LemonButton>
                    )}
                </span>
            ) : props.attributes.runId ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={retry}
                    disabledReason={isPreparing ? 'Preparing dataframe' : undefined}
                >
                    Refresh dataframe
                </LemonButton>
            ) : (
                <span className="text-secondary">Prepared when used</span>
            )}
        </NotebookCellOutputNameFooter>
    )
}
