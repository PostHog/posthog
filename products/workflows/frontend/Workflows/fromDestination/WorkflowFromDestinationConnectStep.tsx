import { useActions, useValues } from 'kea'

import { CyclotronJobInputIntegration } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegration'
import { GuidedWizardSection } from 'lib/components/GuidedWizard/GuidedWizardSection'
import { GuidedWizardStepLayout } from 'lib/components/GuidedWizard/GuidedWizardStepLayout'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { WorkflowFromDestinationLogicProps, workflowFromDestinationLogic } from './workflowFromDestinationLogic'

export function WorkflowFromDestinationConnectStep({
    templateId,
}: WorkflowFromDestinationLogicProps): JSX.Element | null {
    const logic = workflowFromDestinationLogic({ templateId })
    const { integrationInputSchema, inputs, connectError, showValidationErrors } = useValues(logic)
    const { setInput } = useActions(logic)

    if (!integrationInputSchema) {
        return null
    }
    const integrationName = getIntegrationNameFromKind(integrationInputSchema.integration ?? '')

    return (
        <GuidedWizardStepLayout>
            <GuidedWizardSection
                title={`Connect ${integrationName}`}
                description={`Choose the ${integrationName} connection to send from, or connect a new one. ${integrationName} sends you back here after you approve the connection.`}
            />
            <LemonField.Pure
                label={integrationInputSchema.label}
                error={showValidationErrors ? connectError : undefined}
            >
                <CyclotronJobInputIntegration
                    schema={integrationInputSchema}
                    value={inputs?.[integrationInputSchema.key]?.value}
                    onChange={(value) => setInput(integrationInputSchema.key, { value })}
                    connectSurface="workflow_from_destination"
                />
            </LemonField.Pure>
        </GuidedWizardStepLayout>
    )
}
