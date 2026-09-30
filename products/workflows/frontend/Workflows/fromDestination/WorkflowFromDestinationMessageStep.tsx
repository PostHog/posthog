import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { GuidedWizardSection } from 'lib/components/GuidedWizard/GuidedWizardSection'
import { GuidedWizardStepLayout } from 'lib/components/GuidedWizard/GuidedWizardStepLayout'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { WorkflowFromDestinationLogicProps, workflowFromDestinationLogic } from './workflowFromDestinationLogic'

export function WorkflowFromDestinationMessageStep({
    templateId,
}: WorkflowFromDestinationLogicProps): JSX.Element | null {
    const logic = workflowFromDestinationLogic({ templateId })
    const { template, name, inputs, messageInputsSchema, messageErrors, showValidationErrors } = useValues(logic)
    const { setName, setInput } = useActions(logic)

    if (!template) {
        return null
    }

    return (
        <GuidedWizardStepLayout>
            <GuidedWizardSection
                title="Write the message"
                description={`Fill in what ${template.name} sends for each matching event. Event and person properties can be used in the fields.`}
            />
            <LemonField.Pure label="Workflow name">
                <LemonInput value={name ?? ''} onChange={setName} data-attr="workflow-from-destination-name" />
            </LemonField.Pure>
            <CyclotronJobInputs
                configuration={{ inputs_schema: messageInputsSchema, inputs: inputs ?? {} }}
                onInputChange={setInput}
                errors={showValidationErrors ? messageErrors : undefined}
                showSource={false}
                sampleGlobalsWithInputs={null}
            />
        </GuidedWizardStepLayout>
    )
}
