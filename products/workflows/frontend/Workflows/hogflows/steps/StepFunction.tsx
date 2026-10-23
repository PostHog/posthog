import { useActions, useValues } from 'kea'

import { workflowLogic } from '../../workflowLogic'
import { AddToStaticCohortConfiguration } from './components/AddToStaticCohortConfiguration'
import { AiTaskInstructionsCompare } from './components/AiTaskInstructionsCompare'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { OptOutOfMessagesConfiguration } from './components/OptOutOfMessagesConfiguration'
import { SlackRecipientModeConfiguration } from './components/SlackRecipientModeConfiguration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { StepFunctionNode } from './hogFunctionStepLogic'
import { slackRecipientMode, switchSlackRecipientMode } from './slackRecipientMode'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const templateId = node.data.config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = node.data.config.inputs
    const mappings = 'mappings' in node.data.config ? node.data.config.mappings : undefined
    const slackMode = slackRecipientMode(templateId)

    return (
        <>
            <StepSchemaErrors />
            {templateId === 'template-posthog-create-task' && <AiTaskInstructionsCompare actionId={node.id} />}
            {slackMode && (
                <SlackRecipientModeConfiguration
                    mode={slackMode}
                    onChange={(mode) =>
                        mode !== slackMode &&
                        partialSetWorkflowActionConfig(node.id, switchSlackRecipientMode(inputs, mode))
                    }
                />
            )}
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
                    // Remount per node and template: the input renderer snapshots its values on mount, so
                    // switching to another step, or a Slack step to another recipient mode, must remount it.
                    key={`${node.id}:${templateId}`}
                    templateId={templateId}
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
