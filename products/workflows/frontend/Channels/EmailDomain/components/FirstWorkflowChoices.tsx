import { useValues } from 'kea'
import { ReactNode } from 'react'

import { WorkflowDataSuggestions } from '../../../setupGuide/suggestions/WorkflowDataSuggestions'
import { workflowDataSuggestionsLogic } from '../../../setupGuide/suggestions/workflowDataSuggestionsLogic'
import { WorkflowTemplateBlankCard } from '../../../Workflows/templates/WorkflowTemplateBlankCard'
import { emailDomainLogic } from '../emailDomainLogic'
import { CreateWelcomeWorkflowAction } from './CreateWelcomeWorkflowAction'

/** The ways to start a first workflow from the domain wizard: suggestions once loaded, else the welcome template, and always a blank workflow. */
export function FirstWorkflowChoices(): JSX.Element {
    const { offersDataSuggestions } = useValues(emailDomainLogic)

    // The suggestions logic loads on mount, so it only mounts behind the flag.
    return offersDataSuggestions ? <ChoicesWithSuggestions /> : <Choices suggestionsShown={false} />
}

function ChoicesWithSuggestions(): JSX.Element {
    const { cards } = useValues(workflowDataSuggestionsLogic({ surface: 'email_domain_wizard' }))

    // Loaded suggestions replace the welcome template. Until then the template stays the first choice.
    return (
        <Choices suggestionsShown={cards.length > 0}>
            <WorkflowDataSuggestions surface="email_domain_wizard" />
        </Choices>
    )
}

function Choices({ suggestionsShown, children }: { suggestionsShown: boolean; children?: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-5">
            {!suggestionsShown && <CreateWelcomeWorkflowAction data-attr="email-domain-create-welcome-workflow" />}
            <WorkflowTemplateBlankCard data-attr="email-domain-create-blank-workflow" />
            {children}
        </div>
    )
}
