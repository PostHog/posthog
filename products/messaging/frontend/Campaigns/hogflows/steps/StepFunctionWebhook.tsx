import { IconServer, IconWebhooks } from '@posthog/icons'
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
    node: Node<Extract<HogFlowAction, { type: 'function_webhook' }>>
): Promise<CyclotronJobInputSchemaType[]> {
    try {
        const template = await api.hogFunctions.getTemplate(node.data.config.template_id, true)
        return template.inputs_schema || []
    } catch (error) {
        console.error('Failed to fetch template inputs schema:', error)
        return []
    }
}

export const StepFunctionWebhook: HogFlowStep<'function_webhook'> = {
    type: 'function_webhook',
    name: 'Webhook',
    description: 'Send a webhook to an external service.',
    icon: <IconWebhooks />,
    renderNode: (props) => <StepFunctionWebhookNode {...props} />,
    renderConfiguration: (node) => <StepFunctionWebhookConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Webhook',
                description: '',
                type: 'function_webhook',
                on_error: 'continue',
                config: {
                    template_id: 'template-webhook',
                    inputs: {},
                },
            },
        }
    },
}

function StepFunctionWebhookNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepFunctionWebhookConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'function_webhook' }>>
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
