import { cleanup, render } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { InboxUsageWidget } from './InboxUsageWidget'

describe('InboxUsageWidget', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(cleanup)

    it.each(['continue_paid', 'increase_limit'])(
        'shows paid spending and billing access after the trial when continuation is %s',
        async (continuation) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/trial/': {
                        enabled: true,
                        grant_status: 'exhausted',
                        exhaustion_reason: 'report_limit',
                        report_limit: 5,
                        reports_delivered: 5,
                        enabled_scouts: 3,
                        allowance_microusd: 10_000_000,
                        used_microusd: 1_000_000,
                        paid_continuation: continuation,
                    },
                    '/api/billing': {
                        products: [{ type: 'inbox_usage', subscribed: true, current_amount_usd: '1.04' }],
                        usage_summary: { signals_spend_credits: { billing_start_date: '2020-01-01' } },
                    },
                },
            })
            const { findByText } = render(<InboxUsageWidget />)
            expect(await findByText('Your free trial is complete')).toBeTruthy()
            expect(await findByText('Inbox spend')).toBeTruthy()
            expect(await findByText('$1.04')).toBeTruthy()
            expect(await findByText('View usage and limits')).toBeTruthy()
        }
    )
})
