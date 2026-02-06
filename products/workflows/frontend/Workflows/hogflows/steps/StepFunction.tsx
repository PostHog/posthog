import { useActions, useValues } from 'kea'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { StepFunctionNode } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { workflow, actionValidationErrorsById } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const templateId = node.data.config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = node.data.config.inputs
    const mappings = 'mappings' in node.data.config ? node.data.config.mappings : undefined

    const setInputs = (newInputs: Record<string, unknown>): void => {
        const action = workflow?.actions?.find((a) => a.id === node.id)
        const currentInputs = (action?.config as { inputs?: Record<string, unknown> })?.inputs ?? inputs
        partialSetWorkflowActionConfig(node.id, { inputs: { ...currentInputs, ...newInputs } })
    }

    return (
        <>
            <StepSchemaErrors />
            <HogFlowFunctionConfiguration
                templateId={templateId}
                inputs={inputs}
                setInputs={setInputs}
                mappings={mappings}
                setMappings={(mappings) => partialSetWorkflowActionConfig(node.id, { mappings })}
                errors={validationResult?.errors}
            />
        </>
    )
}
