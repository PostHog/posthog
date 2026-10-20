import { useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonCollapse, Spinner } from '@posthog/lemon-ui'

import type { EmailDomainStatusRecordApi } from '../../../generated/api.schemas'
import { emailDomainAutoConfigureLogic } from '../emailDomainAutoConfigureLogic'
import { emailDomainStatusLogic } from '../emailDomainStatusLogic'
import { DnsRecordRows } from './DnsRecordRows'

interface DnsRecordsSummaryProps {
    /** The records to highlight as missing. */
    missing: EmailDomainStatusRecordApi[]
    /** Opens the records, because the person has to fix some of them. */
    needsAttention: boolean
}

function SummaryIcon({ needsAttention }: { needsAttention: boolean }): JSX.Element {
    const { allRecordsFound } = useValues(emailDomainStatusLogic)
    if (allRecordsFound) {
        return <IconCheck className="text-success" />
    }
    return needsAttention ? <IconWarning className="text-warning" /> : <Spinner textColored />
}

/** The DNS records behind one summary line, which a person expands to copy a record. */
export function DnsRecordsSummary({ missing, needsAttention }: DnsRecordsSummaryProps): JSX.Element {
    const { records, foundCount, allRecordsFound } = useValues(emailDomainStatusLogic)
    const { hostName } = useValues(emailDomainAutoConfigureLogic)
    const host = hostName ?? 'your DNS host'
    return (
        <LemonCollapse
            // Remounts when the records start to need attention, so they open for the person to fix.
            key={needsAttention ? 'needs-attention' : 'in-progress'}
            defaultActiveKey={needsAttention ? 'records' : undefined}
            panels={[
                {
                    key: 'records',
                    dataAttr: 'email-domain-dns-records',
                    header: (
                        <span className="flex items-center gap-2">
                            <SummaryIcon needsAttention={needsAttention} />
                            <span>
                                {allRecordsFound
                                    ? `${records.length} settings in place at ${host}`
                                    : `${foundCount} of ${records.length} settings in place at ${host}`}
                            </span>
                        </span>
                    ),
                    content: <DnsRecordRows records={records} missing={missing} showStatus />,
                },
            ]}
        />
    )
}
