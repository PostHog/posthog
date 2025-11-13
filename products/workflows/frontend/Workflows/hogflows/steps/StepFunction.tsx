import { useActions, useValues } from 'kea'

import { CyclotronJobInputType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { StepFunctionNode } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const templateId = node.data.config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = node.data.config.inputs as Record<string, CyclotronJobInputType>

    return (
        <>
            <StepSchemaErrors />
            <HogFlowFunctionConfiguration
                templateId={templateId}
                inputs={inputs}
                setInputs={(inputs) => partialSetWorkflowActionConfig(node.id, { inputs })}
                errors={validationResult?.errors}
            />
        </>
    )
}
