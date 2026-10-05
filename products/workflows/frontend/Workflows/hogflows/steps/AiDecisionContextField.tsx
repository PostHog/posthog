import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCode } from '@posthog/icons'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { hogFlowEditorTestLogic } from '../panel/testing/hogFlowEditorTestLogic'
import { AiDecisionConfig } from './aiDecisionBranches'
import { buildAiDecisionRequestPreview } from './aiDecisionTestRun'
import { buildSampleGlobals } from './components/HogFlowFunctionConfiguration'
import { stepAiDecisionLogic } from './stepAiDecisionLogic'

// Mirrors the server's fixed inputs schema for the step (AI_DECISION_INPUTS_SCHEMA in ai_decision_validation.py).
const CONTEXT_INPUTS_SCHEMA: CyclotronJobInputSchemaType[] = [
    {
        key: 'context',
        type: 'dictionary',
        label: 'What the model sees',
        required: true,
        templating: true,
        description:
            'Only these fields go to the model with the question. Type `{` in a value to fill it in from the person, the event, or a workflow variable.',
    },
]

const CONTEXT_LIMIT_BYTES = 8 * 1024

function formatKilobytes(bytes: number): string {
    return `${(bytes / 1024).toFixed(1)} KB`
}

export function AiDecisionContextField({ config }: { config: AiDecisionConfig }): JSX.Element {
    const { workflow, logicProps } = useValues(workflowLogic)
    const { sampleGlobals } = useValues(hogFlowEditorTestLogic(logicProps))
    const { contextPreview, contextPreviewLoading } = useValues(stepAiDecisionLogic)
    const { updateConfig, loadContextPreview } = useActions(stepAiDecisionLogic)
    const [showRequest, setShowRequest] = useState(false)

    const toggleRequest = (): void => {
        if (!showRequest) {
            loadContextPreview()
        }
        setShowRequest(!showRequest)
    }

    return (
        <div className="flex flex-col gap-2">
            <CyclotronJobInputs
                configuration={{
                    inputs: config.inputs as Record<string, CyclotronJobInputType>,
                    inputs_schema: CONTEXT_INPUTS_SCHEMA,
                }}
                showSource={false}
                sampleGlobalsWithInputs={buildSampleGlobals(workflow?.trigger, workflow?.variables, sampleGlobals)}
                onInputChange={(key, input) => updateConfig({ inputs: { ...config.inputs, [key]: input } })}
            />
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconCode />}
                    onClick={toggleRequest}
                    loading={contextPreviewLoading}
                    tooltip="Runs this step with mocks for the test person. It doesn't ask the model and spends no AI credits."
                    data-attr="workflow-ai-decision-show-request"
                >
                    {showRequest ? 'Hide what is sent' : 'Show what is sent'}
                </LemonButton>
                {contextPreview?.status === 'rendered' && (
                    <div className="flex min-w-40 flex-1 items-center gap-2 text-xs text-secondary">
                        <LemonProgress
                            className="flex-1"
                            percent={(contextPreview.bytes / CONTEXT_LIMIT_BYTES) * 100}
                            strokeColor={contextPreview.bytes > CONTEXT_LIMIT_BYTES ? 'var(--danger)' : undefined}
                        />
                        <span className="whitespace-nowrap tabular-nums">{`${formatKilobytes(contextPreview.bytes)} of ${formatKilobytes(CONTEXT_LIMIT_BYTES)}`}</span>
                    </div>
                )}
            </div>
            {showRequest && contextPreview?.status === 'failed' && (
                <LemonBanner type="error">{contextPreview.message}</LemonBanner>
            )}
            {showRequest && contextPreview?.status === 'rendered' && (
                <pre className="m-0 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded border bg-surface-secondary p-2 text-xs">
                    {buildAiDecisionRequestPreview(config, contextPreview.context)}
                </pre>
            )}
        </div>
    )
}
