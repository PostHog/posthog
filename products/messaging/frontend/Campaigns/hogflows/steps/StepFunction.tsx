import { useActions, useValues } from 'kea'

import { sanitizeInputs } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { CyclotronJobInputType } from '~/types'

import { campaignLogic } from '../../campaignLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { StepFunctionNode } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionValidationErrorsById, hogFunctionTemplatesById } = useValues(campaignLogic)
    const { partialSetCampaignActionConfig } = useActions(campaignLogic)

    const templateId = node.data.config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = node.data.config.inputs as Record<string, CyclotronJobInputType>

    const setInputs = (inputs: Record<string, CyclotronJobInputType>): void => {
        const { inputs_schema } = hogFunctionTemplatesById[node.data.config.template_id]
        partialSetCampaignActionConfig(node.id, { inputs: sanitizeInputs({ inputs_schema, inputs }) })
    }

    return (
        <>
            <StepSchemaErrors />
            <HogFlowFunctionConfiguration
                templateId={templateId}
                inputs={inputs}
                setInputs={setInputs}
                errors={validationResult?.errors}
            />
        </>
    )
}
