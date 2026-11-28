import type { EmailDomainStatusRecordApi } from 'products/integrations/frontend/generated/api.schemas'
import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

// pinned: step key the backend sends for the opt-in domain setup step
export const DOMAIN_SETUP_STEP = 'domain_setup'
const SENDER_PATH = /^\/workflows\/channels\/email\/(\d+)$/
const ZONE_TTL_SECONDS = 3600
// A TXT string holds at most 255 characters, so a longer value is split into several quoted strings.
const TXT_CHUNK_LENGTH = 255

export interface ImportedDomainSender {
    domain: string
    integrationId: number
}

export interface ImportedDomainRecord extends EmailDomainStatusRecordApi {
    domain: string
}

/** The senders the domain setup step added or found, read from the link the step gives each domain. */
export function importedDomainSenders(run: ProviderImportRunApi | null): ImportedDomainSender[] {
    const step = run?.steps.find((candidate) => candidate.key === DOMAIN_SETUP_STEP)
    const senders: ImportedDomainSender[] = []
    for (const item of step?.items ?? []) {
        const match = item.url?.match(SENDER_PATH)
        if (match && (item.status === 'created' || item.status === 'skipped')) {
            senders.push({ domain: item.label, integrationId: Number(match[1]) })
        }
    }
    return senders
}

export function dnsRecordsAsText(records: ImportedDomainRecord[]): string {
    const rows = records.map((record) =>
        [record.domain, record.type, record.hostname, record.priority ?? '', record.value].join('\t')
    )
    return ['Domain\tType\tName\tPriority\tValue', ...rows].join('\n')
}

function absoluteName(name: string): string {
    return name.endsWith('.') ? name : `${name}.`
}

function zoneValue(record: ImportedDomainRecord): string {
    switch (record.type) {
        case 'TXT': {
            const chunks = record.value.match(new RegExp(`.{1,${TXT_CHUNK_LENGTH}}`, 'gs')) ?? ['']
            return chunks.map((chunk) => `"${chunk.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`).join(' ')
        }
        case 'MX':
            return `${record.priority ?? 10} ${absoluteName(record.value)}`
        case 'CNAME':
            return absoluteName(record.value)
    }
}

/** The records in BIND zone file syntax, which most DNS hosts can import. */
export function dnsRecordsAsZoneFile(records: ImportedDomainRecord[]): string {
    const lines = records.map((record) =>
        [absoluteName(record.hostname), ZONE_TTL_SECONDS, 'IN', record.type, zoneValue(record)].join('\t')
    )
    return [`; DNS records for sending email from PostHog`, ...lines, ''].join('\n')
}
