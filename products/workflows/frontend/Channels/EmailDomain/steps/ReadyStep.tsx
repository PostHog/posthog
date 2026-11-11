import { useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonCollapse } from '@posthog/lemon-ui'

import { DnsRecordRows } from '../components/DnsRecordRows'
import { NextWorkflowCard } from '../components/NextWorkflowCard'
import { SenderCard } from '../components/SenderCard'
import { StepHeading } from '../components/StepHeading'
import { emailDomainAutoConfigureLogic } from '../emailDomainAutoConfigureLogic'
import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { emailDomainStatusLogic } from '../emailDomainStatusLogic'
import { HedgehogRocket } from '../hoggies'

export function ReadyStep(): JSX.Element {
    const { domain } = useValues(emailDomainSenderLogic)
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
                ]}
            />
            <NextWorkflowCard />
        </div>
    )
}
