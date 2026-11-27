import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

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
    link_tagging_enabled: true,
    after_click: null,
    without_click: null,
}

describe('AfterClickingCard', () => {
    afterEach(() => {
        cleanup()
    })

    test.each([
        { replay: false, replayVision: false, shows: 'Session replay is off' },
        { replay: true, replayVision: false, shows: null },
        { replay: false, replayVision: true, shows: 'Session replay is off' },
        { replay: true, replayVision: true, shows: 'Where do people get stuck after clicking?' },
    ])(
        'shows what the card can do with session replay on: $replay and Replay vision on: $replayVision',
        async ({ replay, replayVision, shows }) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/transactional_email_log/impact/': () => [200, IMPACT],
                    '/api/projects/:team_id/transactional_email_log/impact_sessions/': () => [
                        200,
                        {
                            sessions: [
                                { session_id: 's-1', message_id: 'm-1', first_pageview_at: '2026-11-26T10:00:00Z' },
                            ],
                            has_more: false,
                        },
                    ],
                },
            })
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: replay })
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                resource_access_control: {
                    ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                    [AccessControlResourceType.ReplayScanner]: AccessControlLevel.Editor,
                    [AccessControlResourceType.SessionRecording]: AccessControlLevel.Viewer,
                },
            } as AppContext
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags(
                replayVision ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_IMPACT_REPLAY_VISION] : [],
                {
                    [FEATURE_FLAGS.WORKFLOWS_EMAIL_IMPACT_REPLAY_VISION]: replayVision,
                }
            )

            render(<EmailImpactTab workflowId={WORKFLOW_ID} alwaysSensitive={false} />)

            await screen.findByText('Sent')
            if (shows) {
                await screen.findByText(shows)
            }
            expect(screen.queryByText('What people did after clicking') !== null).toBe(shows !== null)
        }
    )
})
