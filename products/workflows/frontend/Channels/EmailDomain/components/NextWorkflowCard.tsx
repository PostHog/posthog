import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { HedgehogMailbox } from '../hoggies'
import { FirstWorkflowChoices } from './FirstWorkflowChoices'

export function NextWorkflowCard(): JSX.Element {
    const { domain, senderName, fromAddress, isFirstVerifiedSender } = useValues(emailDomainSenderLogic)
    return (
        <section className="rounded-xl border border-accent bg-accent-highlight-secondary p-6 @md:p-8 flex flex-col gap-5">
            <div className="flex items-start gap-4">
                <HedgehogMailbox className="w-20 shrink-0" />
                <div className="flex flex-col gap-1 min-w-0">
                    <span className="text-xs uppercase tracking-wide text-secondary">Next</span>
                    <h2 className="m-0 text-xl font-semibold">
                        {isFirstVerifiedSender ? 'Send your first email from' : 'Send email from'} {domain}
                    </h2>
                    <p className="m-0 text-sm text-secondary">
                        Start a workflow, and pick <span className="font-medium">{senderName}</span>{' '}
                        <span className="font-mono">&lt;{fromAddress}&gt;</span> as the sender in its emails.
                    </p>
                </div>
            </div>
            <FirstWorkflowChoices />
            <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm">
                <Link to={urls.workflows('library')}>Pick another template</Link>
                <Link to={urls.workflows()}>Go to workflows</Link>
            </div>
        </section>
    )
}
