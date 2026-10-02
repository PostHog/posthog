import { useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonCollapse } from '@posthog/lemon-ui'

import { DnsRecordRows } from '../components/DnsRecordRows'
import { FirstSenderCard } from '../components/FirstSenderCard'
import { NextWorkflowCard } from '../components/NextWorkflowCard'
import { StepHeading } from '../components/StepHeading'
import { emailDomainAutoConfigureLogic } from '../emailDomainAutoConfigureLogic'
import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { emailDomainStatusLogic } from '../emailDomainStatusLogic'
import { HedgehogRocket } from '../hoggies'

export function ReadyStep(): JSX.Element {
    const { domain } = useValues(emailDomainSenderLogic)
    const { records } = useValues(emailDomainStatusLogic)
    const { hostName } = useValues(emailDomainAutoConfigureLogic)
    return (
        <div className="flex flex-col gap-8">
            <div className="rounded-xl border border-success bg-success-highlight p-6 @md:p-8">
                <StepHeading
                    Hoggie={HedgehogRocket}
                    title={
                        <>
                            You can send from <span className="font-mono break-all">{domain}</span>
                        </>
                    }
                    lead={`All ${records.length} settings are in place. Inboxes now know these emails really come from you.`}
                />
            </div>
            <FirstSenderCard />
            <LemonCollapse
                panels={[
                    {
                        key: 'records',
                        header: (
                            <span className="flex items-center gap-2">
                                <IconCheck className="text-success" />
                                {records.length} settings in place at {hostName ?? 'your DNS host'}
                            </span>
                        ),
                        content: <DnsRecordRows records={records} showStatus />,
                    },
                ]}
            />
            <NextWorkflowCard />
        </div>
    )
}
