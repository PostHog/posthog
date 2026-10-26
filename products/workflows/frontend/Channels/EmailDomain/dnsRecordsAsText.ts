import type { EmailDomainStatusRecordApi } from 'products/integrations/frontend/generated/api.schemas'

import { RECORD_KIND_HINT, RECORD_KIND_LABEL } from './components/DnsRecordRows'

const recordAsText = (record: EmailDomainStatusRecordApi): string => {
    const hint = RECORD_KIND_HINT[record.kind]
    return [
        RECORD_KIND_LABEL[record.kind],
        `Type: ${record.type}`,
        `Name: ${record.hostname}`,
        `Value: ${record.value}`,
        ...(record.priority != null ? [`Priority: ${record.priority}`] : []),
        ...(hint ? [`Note: ${hint}`] : []),
    ].join('\n')
}

/** The records as plain text for a DNS owner outside PostHog, who reads them in an email or a chat message. */
export const dnsRecordsAsText = (domain: string, records: EmailDomainStatusRecordApi[]): string =>
    [
        [
            `DNS records for ${domain}`,
            `These records let PostHog send email from ${domain}. Add each one exactly as shown and keep the other DNS records as they are.`,
        ].join('\n'),
        ...records.map(recordAsText),
    ].join('\n\n')
