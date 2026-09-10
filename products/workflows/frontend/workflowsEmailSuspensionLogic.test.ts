import type { EmailSendingAllowanceApi } from 'products/workflows/frontend/generated/api.schemas'

import { resolveReachedEmailSendingCap } from './workflowsEmailSuspensionLogic'

describe('resolveReachedEmailSendingCap', () => {
    const allowance = (overrides: Partial<EmailSendingAllowanceApi> = {}): EmailSendingAllowanceApi =>
        ({
            tier: 0,
            max_tier: 4,
            emails_per_hour: 10,
            emails_per_day: 100,
            max_batch_audience: 100,
            emails_sent_last_hour: 0,
            emails_sent_last_day: 0,
            enforced: true,
            ...overrides,
        }) as EmailSendingAllowanceApi

    it.each([
        {
            name: 'returns null when nothing is loaded yet',
            input: null,
            expected: null,
        },
        {
            name: 'returns null while the tier is measured but not enforced',
            input: allowance({ enforced: false, emails_sent_last_day: 100 }),
            expected: null,
        },
        {
            name: 'returns null below both caps',
            input: allowance({ emails_sent_last_hour: 9, emails_sent_last_day: 99 }),
            expected: null,
        },
        {
            name: 'reports the hourly cap when only the hour is full',
            input: allowance({ emails_sent_last_hour: 10, emails_sent_last_day: 50 }),
            expected: { period: 'hour', limit: 10 },
        },
        {
            name: 'reports the daily cap when both are full',
            input: allowance({ emails_sent_last_hour: 10, emails_sent_last_day: 120 }),
            expected: { period: 'day', limit: 100 },
        },
    ])('$name', ({ input, expected }) => {
        expect(resolveReachedEmailSendingCap(input)).toEqual(expected)
    })
})
