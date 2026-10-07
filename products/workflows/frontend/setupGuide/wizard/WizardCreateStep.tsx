import { useValues } from 'kea'

import { WorkflowTemplateMeta } from '../../Workflows/templates/WorkflowTemplateMeta'
import { WorkflowTemplateSteps } from '../../Workflows/templates/WorkflowTemplateSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

export function WizardCreateStep(): JSX.Element | null {
    const { selectedTemplate } = useValues(workflowsOnboardingWizardLogic)

    if (!selectedTemplate) {
        return null
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <WorkflowTemplateSteps actions={selectedTemplate.actions} edges={selectedTemplate.edges} />
                <h3 className="mb-0 text-base font-semibold">{selectedTemplate.name}</h3>
                {selectedTemplate.description && (
                    <p className="mb-0 text-secondary whitespace-pre-line">{selectedTemplate.description}</p>
                )}
                <WorkflowTemplateMeta template={selectedTemplate} />
            </div>
            <div className="border-t pt-4">
                <h4 className="mb-2 text-sm font-semibold">What happens next</h4>
                <ol className="mb-0 pl-5 list-decimal text-secondary flex flex-col gap-1">
                    <li>We create a draft workflow from this template.</li>
                    <li>You set who it runs for, and test it with a real event.</li>
                    <li>Nothing runs until you launch it.</li>
                </ol>
            </div>
        </div>
    )
}
