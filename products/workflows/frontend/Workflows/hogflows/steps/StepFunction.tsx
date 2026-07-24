import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import {
    LinkedActionTemplate,
    SaveAsTemplateButton,
    StartFromTemplateSelector,
} from './components/StepFunctionActionTemplate'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { StepFunctionNode } from './hogFunctionStepLogic'

export function StepFunctionConfiguration({ node }: { node: StepFunctionNode }): JSX.Element {
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Saved action templates are v1-limited to generic function steps.
    const actionTemplatesEnabled =
        !!featureFlags[FEATURE_FLAGS.WORKFLOWS_ACTION_TEMPLATES] && node.data.type === 'function'

    const config = node.data.config
    const templateId = config.template_id
    const validationResult = actionValidationErrorsById[node.id]
    const inputs = config.inputs
    const mappings = 'mappings' in config ? config.mappings : undefined
    const actionTemplateId = 'action_template_id' in config ? config.action_template_id : undefined
    const detachedFromTemplateId =
        'detached_action_template_id' in config ? config.detached_action_template_id : undefined

    if (actionTemplatesEnabled && actionTemplateId) {
        return (
            <>
                <StepSchemaErrors />
                <LinkedActionTemplate node={node} />
            </>
        )
    }

    return (
        <>
            <StepSchemaErrors />
            {actionTemplatesEnabled && (
                <div className="flex flex-col gap-2 mb-2">
                    {detachedFromTemplateId ? (
                        <LemonBanner type="info">
                            Customized from a saved template — this step no longer receives template updates.
                        </LemonBanner>
                    ) : (
                        <StartFromTemplateSelector node={node} />
                    )}
                    <div>
                        <SaveAsTemplateButton node={node} />
                    </div>
                </div>
            )}
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
            />
        </>
    )
}
