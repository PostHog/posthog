import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { StepSchemaErrors } from './components/StepSchemaErrors'

export function StepAIConfiguration({ node }: { node: Node<Extract<HogFlowAction, { type: 'ai' }>> }): JSX.Element {
    const action = node.data
    const { prompt, model } = action.config

    const { setWorkflowActionConfig } = useActions(workflowLogic)

    return (
        <>
            <StepSchemaErrors />

            <p className="mb-0">Generate content or analyze data using AI.</p>

            <div className="flex flex-col gap-2">
                <div>
                    <label className="font-semibold">Prompt</label>
                    <LemonTextArea
                        value={prompt || ''}
                        onChange={(value) => setWorkflowActionConfig(action.id, { prompt: value })}
                        placeholder="Enter your AI prompt here..."
                        minRows={4}
                    />
                </div>

                <div>
                    <label className="font-semibold">Model</label>
                    <LemonSelect
                        value={model || 'gpt-4-turbo'}
                        onChange={(value) =>
                            setWorkflowActionConfig(action.id, { model: value, prompt: action.config.prompt })
                        }
                        options={[
                            { value: 'gpt-4o', label: 'GPT-4o (128K context)' },
                            { value: 'gpt-4-turbo', label: 'GPT-4 Turbo (128K context)' },
                            { value: 'gpt-4', label: 'GPT-4 (8K context)' },
                            { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo (16K context)' },
                        ]}
                    />
                </div>
            </div>
        </>
    )
}
