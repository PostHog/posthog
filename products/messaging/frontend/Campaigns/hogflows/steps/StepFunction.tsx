import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'

import { CyclotronJobInputType } from '~/types'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { StepFunctionNode, hogFunctionStepLogic } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { configuration, templateLoading, template, configurationValidationErrors } = useValues(
        hogFunctionStepLogic({ node })
    )

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    useEffect(() => {
        setCampaignActionConfig(node.id, {
            inputs: configuration.inputs as Record<string, CyclotronJobInputType>,
        })
    }, [configuration.inputs, template, setCampaignActionConfig, node.id])

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
                    inputs_schema: template.inputs_schema ?? [],
                }}
                showSource={false}
                sampleGlobalsWithInputs={null} // TODO: Load this based on the trigger event
            />
            <div className="text-danger flex items-center gap-1 text-sm">
                {configurationValidationErrors?.inputs && (
                    <div>
                        {Object.entries(configurationValidationErrors.inputs).map(([key, value]) => (
                            <div key={key}>{value}</div>
                        ))}
                    </div>
                )}
            </div>
        </Form>
    )
}
