import type { EmailDomainStatusRecordApi } from 'products/integrations/frontend/generated/api.schemas'

import { dnsRecordsAsText } from './dnsRecordsAsText'

const record = (fields: Omit<EmailDomainStatusRecordApi, 'status'>): EmailDomainStatusRecordApi => ({
    ...fields,
    status: 'pending',
})

describe('dnsRecordsAsText', () => {
    it('writes each record with its purpose, type, name, value, priority and any warning', () => {
        const text = dnsRecordsAsText('mail.acme.com', [
            record({
                kind: 'verification',
                type: 'TXT',
                hostname: '_amazonses.mail.acme.com',
                value: 'token-123',
                priority: null,
            }),
            record({
                kind: 'mail_from_mx',
                type: 'MX',
                hostname: 'feedback.mail.acme.com',
                value: 'feedback-smtp.us-east-1.amazonses.com',
                priority: 10,
            }),
            record({
                kind: 'dmarc',
                type: 'TXT',
                hostname: '_dmarc.mail.acme.com',
                value: 'v=DMARC1; p=none;',
                priority: null,
            }),
        ])

        expect(text).toBe(
            [
                'DNS records for mail.acme.com',
                'These records let PostHog send email from mail.acme.com. Add each one exactly as shown and keep the other DNS records as they are.',
                '',
                'Proves you own the domain',
                'Type: TXT',
                'Name: _amazonses.mail.acme.com',
                'Value: token-123',
                '',
                'Routes bounces back to you (MAIL FROM)',
                'Type: MX',
                'Name: feedback.mail.acme.com',
                'Value: feedback-smtp.us-east-1.amazonses.com',
                'Priority: 10',
                '',
                'Tells inboxes what to do with fakes (DMARC)',
                'Type: TXT',
                'Name: _dmarc.mail.acme.com',
                'Value: v=DMARC1; p=none;',
                'Note: Already have a DMARC record? Keep yours and skip this one.',
            ].join('\n')
        )
    })
})
