import { cleanup, render, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { selfDrivingTrialLogic } from '../../logics/selfDrivingTrialLogic'
import { InboxUsageWidget } from './InboxUsageWidget'

describe('InboxUsageWidget', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SELF_DRIVING_UBP]: true })
    })

    afterEach(cleanup)

    it('keeps paid usage and billing controls when trial status is unavailable', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/trial/': () => [503, { detail: 'Unavailable' }],
                '/api/billing': {
                    products: [
                        { type: 'inbox_usage', subscribed: true, current_amount_usd: '1.04', current_usage: 104 },
                    ],
                    usage_summary: { signals_spend_credits: { billing_start_date: '2020-01-01' } },
                },
            },
        })
        const { findByText, queryByText } = render(<InboxUsageWidget />)
        await waitFor(() =>
            expect(selfDrivingTrialLogic({ teamId: teamLogic.values.currentTeamId! }).values.error).toBeTruthy()
        )
        expect(await findByText('AI credits used')).toBeTruthy()
        expect(await findByText('View usage and limits')).toBeTruthy()
        expect(queryByText('Could not load Self-driving usage. Try again.')).toBeNull()
    })

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
                        reports_in_progress: 0,
                        enabled_scouts: 3,
                        allowance_microusd: 10_000_000,
                        used_microusd: 1_000_000,
                        paid_continuation: continuation,
                        new_work_paused: continuation !== 'continue_paid',
                    },
                    '/api/billing': {
                        products: [
                            { type: 'inbox_usage', subscribed: true, current_amount_usd: '1.04', current_usage: 104 },
                        ],
                        usage_summary: { signals_spend_credits: { billing_start_date: '2020-01-01' } },
                    },
                },
            })
            const { findByText } = render(<InboxUsageWidget />)
            expect(await findByText('Trial limit reached')).toBeTruthy()
            expect(await findByText('Trial allowance used: 100 credits of 1,000 credits.')).toBeTruthy()
            expect(await findByText('AI credits used')).toBeTruthy()
            expect(await findByText('104 credits')).toBeTruthy()
            expect(await findByText('View usage and limits')).toBeTruthy()
        }
    )
})
