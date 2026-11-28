import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { ImportedDomainRecord, dnsRecordsAsZoneFile, importedDomainSenders } from './importedDomainRecords'

const record = (overrides: Partial<ImportedDomainRecord>): ImportedDomainRecord => ({
    domain: 'example.com',
    kind: 'verification',
    hostname: '_amazonses.example.com',
    type: 'TXT',
    value: 'token',
    priority: null,
    status: 'pending',
    ...overrides,
})

describe('importedDomainRecords', () => {
    it('writes each record type in zone file syntax, splitting long TXT values', () => {
        const longValue = `v=DKIM1; p=${'a'.repeat(300)}"`
        const zone = dnsRecordsAsZoneFile([
            record({ value: longValue }),
            record({
                kind: 'mail_from_mx',
                hostname: 'bounce.example.com',
                type: 'MX',
                value: 'feedback-smtp.amazonses.com',
                priority: 10,
            }),
            record({
                kind: 'dkim',
                hostname: 'abc._domainkey.example.com.',
                type: 'CNAME',
                value: 'abc.dkim.amazonses.com',
            }),
        ])

        const [, txt, mx, cname] = zone.split('\n')
        expect(txt).toBe(
            `_amazonses.example.com.\t3600\tIN\tTXT\t"${longValue.slice(0, 255)}" "${longValue.slice(255, -1)}\\""`
        )
        expect(mx).toBe('bounce.example.com.\t3600\tIN\tMX\t10 feedback-smtp.amazonses.com.')
        expect(cname).toBe('abc._domainkey.example.com.\t3600\tIN\tCNAME\tabc.dkim.amazonses.com.')
    })

    it('finds the senders the domain setup step added or found, and no others', () => {
        const item = (label: string, status: string, url: string | null): Record<string, unknown> => ({
            label,
            status,
            url,
            notes: [],
        })
        const run = {
            steps: [
                { key: 'domains', items: [item('listed.example', 'listed', '/workflows/channels/email/9')] },
                {
                    key: 'domain_setup',
                    items: [
                        item('example.com', 'created', '/workflows/channels/email/1'),
                        item('example.org', 'skipped', '/workflows/channels/email/2'),
                        item('failed.example', 'failed', '/workflows/channels'),
                        item('example.net', 'listed', '/workflows/channels'),
                    ],
                },
            ],
        } as unknown as ProviderImportRunApi

        expect(importedDomainSenders(run)).toEqual([
            { domain: 'example.com', integrationId: 1 },
            { domain: 'example.org', integrationId: 2 },
        ])
    })
})
