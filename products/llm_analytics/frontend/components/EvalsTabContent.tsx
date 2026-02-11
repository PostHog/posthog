import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheckCircle, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'
import { llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'
import { llmEvaluationExecutionLogic } from '../llmEvaluationExecutionLogic'
import { GenerationEvalRunsTable } from './GenerationEvalRunsTable'

export function EvalsTabContent({
    generationEventId,
    timestamp,
    event,
    distinctId,
}: {
    generationEventId: string
    timestamp: string
    event: string
    distinctId?: string
}): JSX.Element {
    const generationRunsLogic = useMemo(() => generationEvaluationRunsLogic({ generationEventId }), [generationEventId])

    useAttachedLogic(generationRunsLogic, llmAnalyticsTraceLogic)

    return (
        <EvalsTabContentInner
            generationEventId={generationEventId}
            timestamp={timestamp}
            event={event}
            distinctId={distinctId}
            generationRunsLogic={generationRunsLogic}
        />
    )
}

function EvalsTabContentInner({
    generationEventId,
    timestamp,
    event,
    distinctId,
}: {
    generationEventId: string
    timestamp: string
    event: string
    distinctId?: string
    generationRunsLogic: ReturnType<typeof generationEvaluationRunsLogic.build>
}): JSX.Element {
    const { evaluations, evaluationsLoading } = useValues(llmEvaluationsLogic)
    const { runEvaluation } = useActions(llmEvaluationExecutionLogic)
    const { evaluationRunLoading } = useValues(llmEvaluationExecutionLogic)
    const { refreshGenerationEvaluationRuns, setSelectedEvaluationId } = useActions(generationRunsLogic)
    const { generationEvaluationRunsLoading, selectedEvaluationId } = useValues(generationRunsLogic)

    return (
        <div className="py-4">
            <LemonBanner type="info" className="mb-4">
                Manually triggered evaluations typically appear within seconds, but may take a few minutes to process.
                Click Refresh to see new results.
            </LemonBanner>
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
                                runEvaluation(selectedEvaluationId, generationEventId, timestamp, event, distinctId)
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
            <GenerationEvalRunsTable generationRunsLogic={generationRunsLogic} />
        </div>
    )
}
