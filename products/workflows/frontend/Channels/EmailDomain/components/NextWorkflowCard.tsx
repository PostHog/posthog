import { useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode } from 'react'

import { IconPlus } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { WorkflowDataSuggestions } from '../../../setupGuide/suggestions/WorkflowDataSuggestions'
import { workflowDataSuggestionsLogic } from '../../../setupGuide/suggestions/workflowDataSuggestionsLogic'
import { emailDomainLogic } from '../emailDomainLogic'
import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { HedgehogMailbox } from '../hoggies'
import { BigAction } from './BigAction'

// The id of the "Welcome email sequence" template shipped in products/workflows/backend/templates.
const WELCOME_EMAIL_TEMPLATE_ID = '019b6f44-f9a3-0000-c4a7-b8050d25d690'

export function NextWorkflowCard(): JSX.Element {
    const { offersDataSuggestions } = useValues(emailDomainLogic)

    // The suggestions logic loads on mount, so it only mounts behind the flag.
    return offersDataSuggestions ? <NextWorkflowWithSuggestions /> : <NextWorkflow templateIsPrimary />
}

function NextWorkflowWithSuggestions(): JSX.Element {
    const { cards } = useValues(workflowDataSuggestionsLogic({ surface: 'email_domain_wizard' }))

    // The first suggestion card becomes the one primary button once cards show.
    return (
        <NextWorkflow templateIsPrimary={cards.length === 0}>
            <WorkflowDataSuggestions surface="email_domain_wizard" />
        </NextWorkflow>
    )
}

function NextWorkflow({
    templateIsPrimary,
    children,
}: {
    templateIsPrimary: boolean
    children?: ReactNode
}): JSX.Element {
    const { domain, senderName, fromAddress } = useValues(emailDomainSenderLogic)
    return (
        <section className="rounded-xl border border-accent bg-accent-highlight-secondary p-6 @md:p-8 flex flex-col gap-5">
            <div className="flex items-start gap-4">
                <HedgehogMailbox className="w-20 shrink-0" />
                <div className="flex flex-col gap-1 min-w-0">
                    <span className="text-xs uppercase tracking-wide text-secondary">Next</span>
                    <h2 className="m-0 text-xl font-semibold">Send your first email from {domain}</h2>
                    <p className="m-0 text-sm text-secondary">
                        Start with a welcome email that goes out when someone signs up. We open the Welcome email
                        sequence template so you can pick <span className="font-medium">{senderName}</span>{' '}
                        <span className="font-mono">&lt;{fromAddress}&gt;</span> as the sender.
                    </p>
                </div>
            </div>
            <BigAction
                type={templateIsPrimary ? 'primary' : 'secondary'}
                icon={<IconPlus />}
                onClick={() => router.actions.push(urls.workflowNew(), { templateId: WELCOME_EMAIL_TEMPLATE_ID })}
                data-attr="email-domain-create-welcome-workflow"
            >
                Create the welcome email workflow
            </BigAction>
            {children}
            <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm">
                <Link to={urls.workflows('library')}>Pick another template</Link>
                <Link to={urls.workflows()}>Go to workflows</Link>
            </div>
        </section>
    )
}
