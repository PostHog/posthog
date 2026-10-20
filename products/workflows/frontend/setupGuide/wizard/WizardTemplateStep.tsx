import '../../Workflows/templates/WorkflowTemplateChooser.scss'

import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { WorkflowTemplateCard } from '../../Workflows/templates/WorkflowTemplateCard'
import { WorkflowTemplateMeta } from '../../Workflows/templates/WorkflowTemplateMeta'
import { WorkflowTemplateSteps } from '../../Workflows/templates/WorkflowTemplateSteps'
import { BLANK_START_ID } from './onboardingWizardSteps'
import { WizardSuggestionsStep } from './WizardSuggestionsStep'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

/** A template picker that selects, rather than creates, so the wizard can show more steps before it creates. */
export function WizardTemplateStep(): JSX.Element {
    const {
        templates,
        selectedTemplateId,
        workflowTemplatesLoading,
        startsBlank,
        offersSuggestions,
        suggestionsFirst,
    } = useValues(workflowsOnboardingWizardLogic)
    const { selectTemplate, setTemplatesShown } = useActions(workflowsOnboardingWizardLogic)

    if (workflowTemplatesLoading && templates.length === 0) {
        return (
            <div className="flex justify-center py-6">
                <Spinner className="text-3xl" />
            </div>
        )
    }

    const templateGrid = (
        <div className="WorkflowTemplateChooser">
            <WorkflowTemplateCard
                name="Start from scratch"
                description="Build it yourself on an empty canvas."
                preview={
                    <div className="flex h-full items-center justify-center text-secondary">
                        <IconPlus className="text-3xl" />
                    </div>
                }
                selected={startsBlank}
                onClick={() => selectTemplate(BLANK_START_ID)}
                data-attr="workflows-onboarding-wizard-blank"
            />
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

    if (suggestionsFirst) {
        return <WizardSuggestionsStep fallback={templateGrid} />
    }
    if (!offersSuggestions) {
        return templateGrid
    }
    return (
        <div className="flex flex-col gap-3">
            <div>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={() => setTemplatesShown(false)}
                    data-attr="workflows-onboarding-wizard-show-suggestions"
                >
                    Back to suggestions from your data
                </LemonButton>
            </div>
            {templateGrid}
        </div>
    )
}
