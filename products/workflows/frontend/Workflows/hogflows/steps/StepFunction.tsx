import { useActions, useValues } from 'kea'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { StepFunctionNode } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionValidationErrorsById } = useValues(hogFlowEditorLogic)
    const { partialSetWorkflowActionConfig } = useActions(hogFlowEditorLogic)

    const templateId = node.data.config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = node.data.config.inputs
    const mappings = 'mappings' in node.data.config ? node.data.config.mappings : undefined

    return (
        <>
            <StepSchemaErrors />
            <HogFlowFunctionConfiguration
                templateId={templateId}
                inputs={inputs}
                setInputs={(inputs) => partialSetWorkflowActionConfig(node.id, { inputs })}
                mappings={mappings}
                setMappings={(mappings) => partialSetWorkflowActionConfig(node.id, { mappings })}
                errors={validationResult?.errors}
            />
        </>
    )
}
