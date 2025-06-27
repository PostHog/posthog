import { IconMessage } from '@posthog/icons'
import { Node } from '@xyflow/react'
import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { CyclotronJobInputConfiguration } from 'lib/components/CyclotronJob/types'
import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'
import api from '~/lib/api'

import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

// Function to get inputs schema for a template
async function getNodeInputsSchema(
    node: Node<Extract<HogFlowAction, { type: 'function_sms' }>>
): Promise<CyclotronJobInputSchemaType[]> {
    try {
        const template = await api.hogFunctions.getTemplate(node.data.config.template_id, true)
        return template.inputs_schema || []
    } catch (error) {
        console.error('Failed to fetch template inputs schema:', error)
        return []
    }
}

export const StepFunctionSms: HogFlowStep<'function_sms'> = {
    type: 'function_sms',
    name: 'SMS',
    description: 'Send an SMS to the user.',
    icon: <IconMessage />,
    renderNode: (props) => <StepFunctionSmsNode {...props} />,
    renderConfiguration: (node) => <StepFunctionSmsConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'SMS',
                description: '',
                type: 'function_sms',
                on_error: 'continue',
                config: {
                    template_id: 'template-twilio',
                    inputs: {},
                },
            },
        }
    },
}

function StepFunctionSmsNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepFunctionSmsConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'function_sms' }>>
}): JSX.Element {
    const handleInputChange = (key: string, input: CyclotronJobInputType) => {
        // TODO: Implement input change handler
        console.log('Input changed:', key, input)
    }

    // Convert the inputs to the correct format
    const inputs: Record<string, CyclotronJobInputType> = {}
    Object.entries(node.data.config.inputs).forEach(([key, value]) => {
        inputs[key] = {
            value: value.value,
            templating: value.templating,
            secret: value.secret,
            bytecode: value.bytecode,
        }
    })

    return (
        <CyclotronJobInputs
            configuration={{
                inputs,
                inputs_schema: [], // This will be populated by getNodeInputsSchema
            }}
            onInputChange={handleInputChange}
            showSource={false}
        />
    )
}
