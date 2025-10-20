import { useActions, useValues } from 'kea'
import React from 'react'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import { llmEvaluationExecutionLogic } from '../llmEvaluationExecutionLogic'

interface EvaluationRunModalProps {
    visible: boolean
    targetEventId: string
    onClose: () => void
}

export function EvaluationRunModal({ visible, targetEventId, onClose }: EvaluationRunModalProps): JSX.Element {
    const { evaluations, evaluationsLoading } = useValues(llmEvaluationsLogic)
    const { runEvaluation } = useActions(llmEvaluationExecutionLogic)
    const { evaluationRunLoading } = useValues(llmEvaluationExecutionLogic)

    const [selectedEvaluationId, setSelectedEvaluationId] = React.useState<string | null>(null)

    const handleRun = (): void => {
        if (selectedEvaluationId) {
            runEvaluation(selectedEvaluationId, targetEventId)
            onClose()
        }
    }

    return (
        <LemonModal
            isOpen={visible}
            onClose={onClose}
            title="Run Evaluation"
            description="Select an evaluation to run on this generation"
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleRun}
                        loading={evaluationRunLoading}
                        disabledReason={!selectedEvaluationId ? 'Please select an evaluation' : undefined}
                    >
                        Run Evaluation
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="block text-sm font-medium mb-2">Select Evaluation</label>
                    <LemonSelect
                        value={selectedEvaluationId}
                        onChange={setSelectedEvaluationId}
                        options={
                            evaluations
                                ?.filter((e) => !e.deleted)
                                .map((evaluation) => ({
                                    value: evaluation.id,
                                    label: evaluation.name,
                                })) || []
                        }
                        placeholder="Choose an evaluation..."
                        loading={evaluationsLoading}
                        fullWidth
                    />
                </div>

                <div className="text-sm text-muted">
                    <p>
                        The evaluation will be executed asynchronously. Results will appear in the evaluation runs table
                        once complete.
                    </p>
                </div>
            </div>
        </LemonModal>
    )
}
