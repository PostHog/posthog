import { useActions, useValues } from 'kea'

import { workflowLogic } from '../../workflowLogic'
import { AddToStaticCohortConfiguration } from './components/AddToStaticCohortConfiguration'
import { AiTaskInstructionsCompare } from './components/AiTaskInstructionsCompare'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { OptOutOfMessagesConfiguration } from './components/OptOutOfMessagesConfiguration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { StepFunctionNode } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const templateId = node.data.config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = node.data.config.inputs
    const mappings = 'mappings' in node.data.config ? node.data.config.mappings : undefined

    return (
        <>
            <StepSchemaErrors />
            {templateId === 'template-posthog-create-task' && <AiTaskInstructionsCompare actionId={node.id} />}
            {templateId === 'template-posthog-opt-out-of-messages' && (
                <OptOutOfMessagesConfiguration
                    inputs={inputs}
                    setInputs={(inputs) => partialSetWorkflowActionConfig(node.id, { inputs })}
                    error={validationResult?.errors?.category_id}
                />
            )}
            {templateId === 'template-posthog-add-to-static-cohort' ? (
                <AddToStaticCohortConfiguration
                    inputs={inputs}
                    setInputs={(inputs) => partialSetWorkflowActionConfig(node.id, { inputs })}
                    error={validationResult?.errors?.cohort_id}
                />
            ) : (
                <HogFlowFunctionConfiguration
                    // Remount per node: the input renderer snapshots its values on mount, so switching to
                    // another step of the same template must remount to show the newly selected node's inputs.
                    key={node.id}
                    templateId={templateId}
                    actionType={node.data.type}
                    inputs={inputs}
                    setInputs={(inputs) => partialSetWorkflowActionConfig(node.id, { inputs })}
                    mappings={mappings}
                    setMappings={(mappings) => partialSetWorkflowActionConfig(node.id, { mappings })}
                    errors={validationResult?.errors}
                    warnings={validationResult?.warnings}
                    emailFieldErrors={validationResult?.emailErrors}
                />
            )}
        </>
    )
}
