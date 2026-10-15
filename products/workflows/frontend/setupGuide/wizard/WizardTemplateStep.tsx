import '../../Workflows/templates/WorkflowTemplateChooser.scss'

import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { WorkflowTemplateCard } from '../../Workflows/templates/WorkflowTemplateCard'
import { WorkflowTemplateMeta } from '../../Workflows/templates/WorkflowTemplateMeta'
import { WorkflowTemplateSteps } from '../../Workflows/templates/WorkflowTemplateSteps'
import { WorkflowDataSuggestions } from '../suggestions/WorkflowDataSuggestions'
import { BLANK_START_ID } from './onboardingWizardSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

/** A template picker that selects, rather than creates, so the wizard can show more steps before it creates. */
export function WizardTemplateStep(): JSX.Element {
    const { templates, selectedTemplateId, workflowTemplatesLoading, startsBlank, wizardPath } =
        useValues(workflowsOnboardingWizardLogic)
    const { selectTemplate } = useActions(workflowsOnboardingWizardLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    // The suggestions logic starts an AI run on mount, so it only mounts behind the flag. Suggestions are messages
    // to users, so the automation path keeps the plain template list.
    const showSuggestions = wizardPath === 'messaging' && !!featureFlags[FEATURE_FLAGS.WORKFLOWS_DATA_SUGGESTIONS]

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

    if (!showSuggestions) {
        return templateGrid
    }

    return (
        <div className="flex flex-col gap-6">
            <WorkflowDataSuggestions surface="onboarding_wizard" />
            {templateGrid}
        </div>
    )
}
