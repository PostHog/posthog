import { useActions, useValues } from 'kea'

import { workflowLogic } from '../../workflowLogic'
import { AddToStaticCohortConfiguration } from './components/AddToStaticCohortConfiguration'
import { AiTaskInstructionsCompare } from './components/AiTaskInstructionsCompare'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { OptOutOfMessagesConfiguration } from './components/OptOutOfMessagesConfiguration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { SandboxSenderChoiceProvider } from './email/SandboxSenderChoiceProvider'
import { StepFunctionNode } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const templateId = node.data.config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = node.data.config.inputs
    const mappings = 'mappings' in node.data.config ? node.data.config.mappings : undefined

    const functionConfiguration = (
        <HogFlowFunctionConfiguration
            key={node.id}
            templateId={templateId}
            inputs={inputs}
            setInputs={(inputs) => partialSetWorkflowActionConfig(node.id, { inputs })}
            mappings={mappings}
            setMappings={(mappings) => partialSetWorkflowActionConfig(node.id, { mappings })}
            errors={validationResult?.errors}
            warnings={validationResult?.warnings}
            emailFieldErrors={validationResult?.emailErrors}
        />
    )

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
            ) : node.data.type === 'function_email' ? (
                <SandboxSenderChoiceProvider actionId={node.id}>{functionConfiguration}</SandboxSenderChoiceProvider>
            ) : (
                functionConfiguration
            )}
        </>
    )
}
