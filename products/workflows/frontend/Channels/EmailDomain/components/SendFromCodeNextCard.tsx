import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { emailDomainLogic } from '../emailDomainLogic'
import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { HedgehogMailbox } from '../hoggies'

export function SendFromCodeNextCard(): JSX.Element {
    const { domain } = useValues(emailDomainSenderLogic)
    const { originConfig } = useValues(emailDomainLogic)
    return (
        <section className="rounded-xl border border-accent bg-accent-highlight-secondary p-6 @md:p-8 flex flex-col gap-5">
            <div className="flex items-start gap-4">
                <HedgehogMailbox className="w-20 shrink-0" />
                <div className="flex flex-col gap-1 min-w-0">
                    <span className="text-xs uppercase tracking-wide text-secondary">Next</span>
                    <h2 className="m-0 text-xl font-semibold">
                        Send email from <span className="inline-block max-w-full wrap-anywhere">{domain}</span> in your
                        code
                    </h2>
                    <p className="m-0 text-sm text-secondary">
                        Go back to transactional emails to add the first send to your server code.
                    </p>
                </div>
            </div>
            <LemonButton
                type="primary"
                className="self-start"
                to={originConfig.backUrl}
                data-attr="email-domain-ready-back-to-origin"
            >
                {originConfig.backLabel}
            </LemonButton>
        </section>
    )
}
