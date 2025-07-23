import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { CyclotronJobInputType } from '~/types'

import { hogFunctionStepLogic, StepFunctionNode } from './hogFunctionStepLogic'
import { Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { configuration, templateLoading, template } = useValues(hogFunctionStepLogic({ node }))

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    useEffect(() => {
        setCampaignActionConfig(node.id, {
            inputs: configuration.inputs,
        })
    }, [configuration.inputs, setCampaignActionConfig, node.id])

    if (templateLoading) {
        return (
            <div className="flex justify-center items-center">
                <Spinner />
            </div>
        )
    }

    if (!template) {
        return <div>Template not found!</div>
    }

    return (
        <Form logic={hogFunctionStepLogic} props={{ node }} formKey="configuration" className="flex flex-col gap-2">
            <CyclotronJobInputs
                configuration={{
                    inputs: node.data.config.inputs as Record<string, CyclotronJobInputType>,
                    inputs_schema: template?.inputs_schema ?? [],
                }}
                showSource={false}
                sampleGlobalsWithInputs={null} // TODO: Load this based on the trigger event
            />
        </Form>
    )
}
