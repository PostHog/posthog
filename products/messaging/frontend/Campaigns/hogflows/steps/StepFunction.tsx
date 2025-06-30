import { Node } from '@xyflow/react'
import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { CyclotronJobInputType } from '~/types'

import { HogFlowAction } from '../types'
import { hogFunctionStepLogic } from './hogFunctionStepLogic'
import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'

export function StepFunctionConfiguration({
    node,
}: {
    node: Node<
        Extract<
            HogFlowAction,
            | { type: 'function_email' }
            | { type: 'function_slack' }
            | { type: 'function_sms' }
            | { type: 'function_webhook' }
        >
    >
}): JSX.Element {
    const logic = hogFunctionStepLogic({ id: node.id, templateId: node.data.config.template_id })
    logic.mount()
    const { templateLoading, template } = useValues(logic)

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

    if (templateLoading) {
        return (
            <div className="flex items-center justify-center">
                <Spinner />
            </div>
        )
    }

    return (
        <Form
            logic={hogFunctionStepLogic}
            props={{ id: node.id, templateId: node.data.config.template_id }}
            formKey="configuration"
            className="flex flex-col gap-2"
        >
            <CyclotronJobInputs
                configuration={{
                    inputs,
                    inputs_schema: template?.inputs_schema ?? [],
                }}
                onInputChange={handleInputChange}
                showSource={false}
            />
        </Form>
    )
}
