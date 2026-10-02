import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { AnotherDomainInput } from '../components/AnotherDomainInput'
import { BigAction } from '../components/BigAction'
import { DomainCard } from '../components/DomainCard'
import { SendingAddressCard } from '../components/SendingAddressCard'
import { StepHeading } from '../components/StepHeading'
import { EmailDomainWizardLogicProps, emailDomainWizardLogic } from '../emailDomainWizardLogic'
import { HedgehogMailbox } from '../hoggies'

function DomainChoices(props: EmailDomainWizardLogicProps): JSX.Element {
    const logic = emailDomainWizardLogic(props)
    const { inferredDomains, eventHostsLoading, selectedDomain, selectedIsInferred } = useValues(logic)
    const { selectDomain, clearDomain } = useActions(logic)
    return (
        <div className="flex flex-col gap-3">
            {eventHostsLoading && inferredDomains.length === 0 && <LemonSkeleton className="h-20" />}
            {inferredDomains.map((candidate) => (
                <DomainCard
                    key={candidate.domain}
                    {...candidate}
                    selected={selectedDomain === candidate.domain}
                    onSelect={() => selectDomain(candidate.domain)}
                />
            ))}
            {selectedDomain && !selectedIsInferred && (
                <DomainCard
                    domain={selectedDomain}
                    reasons={['You typed this one']}
                    recommended={false}
                    selected
                    onSelect={clearDomain}
                />
            )}
        </div>
    )
}

function CreateSender(props: EmailDomainWizardLogicProps): JSX.Element {
    const logic = emailDomainWizardLogic(props)
    const { existingSender, submitError, createdSenderLoading, bouncePrefix } = useValues(logic)
    const { clearDomain, createSender } = useActions(logic)
    const disabledReason = createdSenderLoading
        ? 'Creating the sender'
        : existingSender
          ? 'A sender for this domain already exists'
          : !bouncePrefix
            ? 'Type a bounce subdomain'
            : undefined
    return (
        <>
            {existingSender && (
                <p className="m-0 text-sm text-center text-secondary">
                    A sender for this domain already exists in this project.{' '}
                    <Link to={urls.workflowsEmailDomain(existingSender.id)}>Open it</Link> to add settings or check its
                    status.
                </p>
            )}
            {submitError && <p className="m-0 text-sm text-center text-danger">{submitError}</p>}
            <div className="flex flex-col items-center gap-2">
                <BigAction
                    onClick={createSender}
                    sideIcon={<IconArrowRight />}
                    loading={createdSenderLoading}
                    disabledReason={disabledReason}
                    data-attr="email-domain-continue"
                >
                    Continue
                </BigAction>
                <LemonButton type="tertiary" size="small" onClick={clearDomain}>
                    Another domain
                </LemonButton>
            </div>
        </>
    )
}

export function DomainStep(props: EmailDomainWizardLogicProps): JSX.Element {
    const { inferredDomains, eventHostsLoading, selectedDomain } = useValues(emailDomainWizardLogic(props))
    const lead =
        eventHostsLoading || inferredDomains.length > 0
            ? 'We looked at your project and found these. Pick one or type your own.'
            : 'Type the domain your emails should come from.'

    return (
        <div className="flex flex-col gap-8">
            <StepHeading Hoggie={HedgehogMailbox} title="Which domain should your emails come from?" lead={lead} />
            <DomainChoices {...props} />
            {selectedDomain ? (
                <>
                    <SendingAddressCard {...props} />
                    <CreateSender {...props} />
                </>
            ) : (
                <AnotherDomainInput {...props} />
            )}
        </div>
    )
}
