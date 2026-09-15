import { DnsRecord, dnsRecordsToClipboardText, parseHostname } from './emailSetupModalLogic'

const record = (overrides: Partial<DnsRecord>): DnsRecord => ({
    type: 'dkim',
    status: 'pending',
    recordType: 'CNAME',
    recordValue: 'abc.dkim.amazonses.com',
    recordHostname: 'abc._domainkey.example.com',
    parsedHostname: parseHostname('abc._domainkey.example.com', 'example.com'),
    ...overrides,
})

describe('dnsRecordsToClipboardText', () => {
    it('renders a tab separated table without a priority column', () => {
        expect(
            dnsRecordsToClipboardText([record({}), record({ recordType: 'TXT', recordHostname: 'example.com' })])
        ).toEqual(
            [
                'Type\tName\tValue',
                'CNAME\tabc._domainkey.example.com\tabc.dkim.amazonses.com',
                'TXT\texample.com\tabc.dkim.amazonses.com',
            ].join('\n')
        )
    })

    it('adds a priority column when at least one record has a priority', () => {
        expect(
            dnsRecordsToClipboardText([
                record({}),
                record({
                    recordType: 'MX',
                    recordHostname: 'feedback.example.com',
                    recordValue: 'feedback-smtp.us-east-1.amazonses.com',
                    priority: 10,
                }),
            ])
        ).toEqual(
            [
                'Type\tName\tValue\tPriority',
                'CNAME\tabc._domainkey.example.com\tabc.dkim.amazonses.com\t',
                'MX\tfeedback.example.com\tfeedback-smtp.us-east-1.amazonses.com\t10',
            ].join('\n')
        )
    })

    it('returns only the header when there are no records', () => {
        expect(dnsRecordsToClipboardText([])).toEqual('Type\tName\tValue')
    })
})
