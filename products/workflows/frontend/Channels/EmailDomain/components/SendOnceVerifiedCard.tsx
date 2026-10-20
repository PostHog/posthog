import { useValues } from 'kea'

import { LemonCard, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { HedgehogMailbox } from '../hoggies'
import { FirstWorkflowChoices } from './FirstWorkflowChoices'

export function SendOnceVerifiedCard(): JSX.Element {
    const { domain } = useValues(emailDomainSenderLogic)
    return (
        <LemonCard hoverEffect={false} className="rounded-xl @md:p-8 flex flex-col gap-5">
            <div className="flex items-start gap-4">
                <HedgehogMailbox className="w-20 shrink-0" />
                <div className="flex flex-col gap-1 min-w-0">
                    <span className="text-xs uppercase tracking-wide text-secondary">While you wait</span>
                    <h2 className="m-0 text-xl font-semibold">Turn on your workflows now</h2>
                    <p className="m-0 text-sm text-secondary">
                        You can turn on workflows that send from <span className="font-mono break-all">{domain}</span>{' '}
                        now. They start sending once the domain is verified.
                    </p>
                </div>
            </div>
            <FirstWorkflowChoices placement="verifying" />
            <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm">
                <Link to={urls.workflows()} data-attr="email-domain-verifying-go-to-workflows">
                    Go to workflows
                </Link>
            </div>
        </LemonCard>
    )
}
