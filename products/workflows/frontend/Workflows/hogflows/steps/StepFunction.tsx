import { useActions, useValues } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { workflowLogic } from '../../workflowLogic'
import { savedFunctionTemplatesLogic } from '../savedFunctionTemplatesLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { SaveFunctionAsTemplateModal } from './components/SaveFunctionAsTemplateModal'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { StepFunctionNode } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionValidationErrorsById, hogFunctionTemplatesById } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)
    const { openSaveModal } = useActions(savedFunctionTemplatesLogic)

    const templateId = node.data.config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = node.data.config.inputs
    const mappings = 'mappings' in node.data.config ? node.data.config.mappings : undefined

    // Only generic destination steps can be saved to the library - email/SMS/push have their own flows
    const template = hogFunctionTemplatesById[templateId]
    const canSaveAsTemplate = node.data.type === 'function' && template?.type === 'destination'

    return (
        <>
            <StepSchemaErrors />
            <HogFlowFunctionConfiguration
                // Remount per node: the input renderer snapshots its values on mount, so switching to
                // another step of the same template must remount to show the newly selected node's inputs.
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
            {canSaveAsTemplate && (
                <>
                    <LemonDivider className="my-2" />
                    <div className="flex flex-col gap-1">
                        <LemonButton
                            type="secondary"
                            icon={<IconBookmark />}
                            onClick={openSaveModal}
                            fullWidth
                            center
                            data-attr="workflow-step-save-to-library"
                        >
                            Save step to library
                        </LemonButton>
                        <p className="mb-0 text-xs text-secondary">
                            Add this step to your template library so you can drop it into other workflows without
                            setting it up again.
                        </p>
                    </div>
                    <SaveFunctionAsTemplateModal template={template} inputs={inputs} mappings={mappings} />
                </>
            )}
        </>
    )
}
