import { useValues } from 'kea'

import { IconCheck, IconInfo, IconWarning } from '@posthog/icons'
import { LemonCollapse, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DnsRecordRows } from '../components/DnsRecordRows'
import { NextWorkflowCard } from '../components/NextWorkflowCard'
import { SenderCard } from '../components/SenderCard'
import { SendFromCodeNextCard } from '../components/SendFromCodeNextCard'
import { StepHeading } from '../components/StepHeading'
import { emailDomainAutoConfigureLogic } from '../emailDomainAutoConfigureLogic'
import { emailDomainLogic } from '../emailDomainLogic'
import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { EmailDomainSetupOrigin } from '../emailDomainSetupOrigin'
import { emailDomainStatusLogic } from '../emailDomainStatusLogic'
import { HedgehogRocket } from '../hoggies'

const REPUTATION_URL: Record<EmailDomainSetupOrigin, () => string> = {
    workflows: () => urls.workflows('reputation'),
    transactional: () => urls.transactional('reputation'),
}

const NEXT_STEP: Record<EmailDomainSetupOrigin, () => JSX.Element> = {
    workflows: NextWorkflowCard,
    transactional: SendFromCodeNextCard,
}

export function ReadyStep({ nextStep }: { nextStep?: JSX.Element }): JSX.Element {
    const { domain } = useValues(emailDomainSenderLogic)
    const { origin } = useValues(emailDomainLogic)
    const NextStep = NEXT_STEP[origin]
    const { records, foundCount, allRecordsFound } = useValues(emailDomainStatusLogic)
    const { hostName } = useValues(emailDomainAutoConfigureLogic)
    const host = hostName ?? 'your DNS host'
    return (
        <div className="flex flex-col gap-8">
            <div className="rounded-xl border border-success bg-success-highlight p-6 @md:p-8">
                <StepHeading
                    Hoggie={HedgehogRocket}
                    title={
                        <>
                            You can send from <span className="inline-block max-w-full wrap-anywhere">{domain}</span>
                        </>
                    }
                    lead={
                        allRecordsFound
                            ? `All ${records.length} settings are in place. Inboxes now know these emails really come from you.`
                            : `The email provider verified this domain. ${foundCount} of ${records.length} settings are in place, so add the rest at ${host}.`
                    }
                />
            </div>
            <SenderCard />
            <LemonCollapse
                defaultActiveKey={allRecordsFound ? undefined : 'records'}
                panels={[
                    {
                        key: 'records',
                        header: (
                            <span className="flex items-center gap-2">
                                {allRecordsFound ? (
                                    <IconCheck className="text-success" />
                                ) : (
                                    <IconWarning className="text-warning" />
                                )}
                                <span>
                                    {allRecordsFound
                                        ? `${records.length} settings in place at ${host}`
                                        : `${foundCount} of ${records.length} settings in place at ${host}`}
                                </span>
                            </span>
                        ),
                        content: (
                            <DnsRecordRows
                                records={records}
                                missing={records.filter((record) => record.status === 'pending')}
                                showStatus
                            />
                        ),
                    },
                    {
                        key: 'reputation',
                        header: (
                            <span className="flex items-center gap-2">
                                <IconInfo className="text-secondary" />
                                <span>Keep your emails out of spam</span>
                            </span>
                        ),
                        content: (
                            <div className="flex flex-col gap-3 text-sm">
                                <ul className="m-0 pl-5 list-disc flex flex-col gap-1.5">
                                    <li>
                                        Start small. Send to the people most likely to open first, then grow the volume
                                        over a few weeks.
                                    </li>
                                    <li>
                                        Only email people who asked to hear from you. Old or bought lists bounce and get
                                        marked as spam.
                                    </li>
                                    <li>
                                        Make it easy to unsubscribe. People who can't find the link mark the email as
                                        spam instead.
                                    </li>
                                    <li>
                                        PostHog stops sending to addresses that can't receive email or that report spam,
                                        so you don't need to clean those up yourself.
                                    </li>
                                </ul>
                                <span className="text-secondary">
                                    Track bounces and spam reports on the{' '}
                                    <Link to={REPUTATION_URL[origin]()} data-attr="email-domain-ready-reputation">
                                        Reputation
                                    </Link>{' '}
                                    page.
                                </span>
                            </div>
                        ),
                    },
                ]}
            />
            {nextStep ?? <NextStep />}
        </div>
    )
}
