import '../../Workflows/templates/WorkflowTemplateChooser.scss'

import { useActions, useValues } from 'kea'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { WorkflowTemplateCard } from '../../Workflows/templates/WorkflowTemplateCard'
import { WorkflowTemplateMeta } from '../../Workflows/templates/WorkflowTemplateMeta'
import { WorkflowTemplateSteps } from '../../Workflows/templates/WorkflowTemplateSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

/** A template picker that selects, rather than creates, so the wizard can show more steps before it creates. */
export function WizardTemplateStep(): JSX.Element {
    const { templates, selectedTemplateId, workflowTemplatesLoading } = useValues(workflowsOnboardingWizardLogic)
    const { selectTemplate } = useActions(workflowsOnboardingWizardLogic)

    if (workflowTemplatesLoading && templates.length === 0) {
        return (
            <div className="flex justify-center py-6">
                <Spinner className="text-3xl" />
            </div>
        )
    }

    return (
        <div className="WorkflowTemplateChooser">
            {templates.map((template) => (
                <WorkflowTemplateCard
                    key={template.id}
                    name={template.name || 'Unnamed template'}
                    description={template.description}
                    preview={<WorkflowTemplateSteps actions={template.actions} edges={template.edges} />}
                    footer={<WorkflowTemplateMeta template={template} />}
                    selected={template.id === selectedTemplateId}
                    onClick={() => selectTemplate(template.id)}
                    data-attr="workflows-onboarding-wizard-template"
                />
            ))}
        </div>
    )
}
