import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { EmailImpactTab } from './EmailImpactTab'

const WORKFLOW_ID = '0192c3a4-5b6c-7d8e-9f01-23456789abcd'

const IMPACT: TransactionalEmailImpactApi = {
    sent: 10,
    delivered: 9,
    opened: 5,
    clicked: 2,
    not_clicked: 7,
    untracked: 0,
    clicks_untracked: 0,
    window_days: 7,
    sessions: 2,
    sessions_capped_at: null,
    link_tagging_enabled: true,
    after_click: null,
    without_click: null,
}

const REPLAY_OFF_COPY =
    'Replay vision will watch the sessions this email starts and group what people did. It needs session replay to record those sessions.'

describe('AfterClickingCard', () => {
    afterEach(() => {
        cleanup()
    })

    test.each([
        { replay: false, shown: true },
        { replay: true, shown: false },
    ])('shows the card only while session replay is off (replay on: $replay)', async ({ replay, shown }) => {
        useMocks({
            get: { '/api/projects/:team_id/transactional_email_log/impact/': () => [200, IMPACT] },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: replay })

        render(<EmailImpactTab workflowId={WORKFLOW_ID} alwaysSensitive={false} />)

        await screen.findByText('Sent')
        expect(screen.queryByText('What people did after clicking') !== null).toBe(shown)
        expect(screen.queryByText(REPLAY_OFF_COPY) !== null).toBe(shown)
    })
})
