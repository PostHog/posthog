import { BindLogic, useActions, useValues } from 'kea'

import { IconCheckCircle, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'
import { llmEvaluationExecutionLogic } from '../llmEvaluationExecutionLogic'
import { GenerationEvalRunsTable } from './GenerationEvalRunsTable'

export function EvalsTabContent({
    generationEventId,
    timestamp,
}: {
    generationEventId: string
    timestamp: string
}): JSX.Element {
    return (
        <BindLogic logic={generationEvaluationRunsLogic} props={{ generationEventId }}>
            <EvalsTabContentInner generationEventId={generationEventId} timestamp={timestamp} />
        </BindLogic>
    )
}

function EvalsTabContentInner({
    generationEventId,
    timestamp,
}: {
    generationEventId: string
    timestamp: string
}): JSX.Element {
    const { evaluations, evaluationsLoading } = useValues(llmEvaluationsLogic)
    const { runEvaluation } = useActions(llmEvaluationExecutionLogic)
    const { evaluationRunLoading } = useValues(llmEvaluationExecutionLogic)
    const { refreshGenerationEvaluationRuns, setSelectedEvaluationId } = useActions(generationEvaluationRunsLogic)
    const { generationEvaluationRunsLoading, selectedEvaluationId } = useValues(generationEvaluationRunsLogic)

    return (
        <div className="py-4">
            <div className="flex justify-between items-center mb-4">
                <div className="flex gap-2">
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
                        placeholder="Select an evaluation to run"
                        loading={evaluationsLoading}
                        className="w-80"
                    />
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconCheckCircle />}
                        onClick={() => {
                            if (selectedEvaluationId) {
                                runEvaluation(selectedEvaluationId, generationEventId, timestamp)
                            }
                        }}
                        loading={evaluationRunLoading}
                        disabledReason={!selectedEvaluationId ? 'Select an evaluation first' : undefined}
                        data-attr="run-evaluation-manual"
                    >
                        Run Evaluation
                    </LemonButton>
                </div>
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={refreshGenerationEvaluationRuns}
                    loading={generationEvaluationRunsLoading}
                    size="small"
                >
                    Refresh
                </LemonButton>
            </div>
            <GenerationEvalRunsTable generationEventId={generationEventId} />
        </div>
    )
}
