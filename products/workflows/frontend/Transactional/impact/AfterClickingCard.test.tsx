import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { emailImpactLogic } from './emailImpactLogic'
import { EmailImpactTab } from './EmailImpactTab'

const WORKFLOW_ID = '0192c3a4-5b6c-7d8e-9f01-23456789abcd'
const READY = 'Ask Replay vision about these sessions'
const TRACKING_OFF = {
    ...MOCK_DEFAULT_TEAM,
    session_recording_opt_in: true,
    workflows_config: { ...MOCK_DEFAULT_TEAM.workflows_config, email_workflow_run_link_tag_enabled: false },
}

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
    let sessionsDateFroms: (string | null)[]

    beforeEach(() => {
        sessionsDateFroms = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': () => [200, IMPACT],
                '/api/projects/:team_id/transactional_email_log/impact_sessions/': ({ request }) => {
                    sessionsDateFroms.push(new URL(request.url).searchParams.get('date_from'))
                    return [
                        200,
                        {
                            sessions: [
                                { session_id: 's-1', message_id: 'm-1', first_pageview_at: '2026-11-26T10:00:00Z' },
                            ],
                            has_more: false,
                        },
                    ]
                },
            },
            post: {
                '/api/projects/:team_id/vision/requests/': () => [
                    202,
                    {
                        id: '01a21d51-012a-7d3d-a576-b38b7254d78a',
                        status: 'completed',
                        scanner_id: 'scanner-1',
                        reference: `workflows-email:${WORKFLOW_ID}`,
                        created_at: '2026-11-27T10:00:00Z',
                        sessions: [
                            {
                                session_id: 's-1',
                                scan_outcome: 'started',
                                state: 'succeeded',
                                observation_id: null,
                                scanner_result: {
                                    model_output: { verdict: 'yes', reasoning: 'They booked a demo.' },
                                    signals_count: 0,
                                },
                            },
                        ],
                    },
                ],
            },
        })
    })

    function renderTab(team: typeof MOCK_DEFAULT_TEAM, replayVision: boolean): void {
        initKeaTests(true, team)
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
            { [FEATURE_FLAGS.WORKFLOWS_EMAIL_IMPACT_REPLAY_VISION]: replayVision }
        )
        render(<EmailImpactTab workflowId={WORKFLOW_ID} alwaysSensitive={false} />)
    }

    afterEach(() => {
        cleanup()
    })

    test.each([
        { replay: false, replayVision: false, shows: 'Session replay is off' },
        { replay: true, replayVision: false, shows: null },
        { replay: false, replayVision: true, shows: 'Session replay is off' },
        { replay: true, replayVision: true, shows: READY },
    ])(
        'shows what the card can do with session replay on: $replay and Replay vision on: $replayVision',
        async ({ replay, replayVision, shows }) => {
            renderTab({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: replay }, replayVision)

            await screen.findByText('Sent')
            if (shows) {
                await screen.findByText(shows)
            }
            expect(screen.queryByText('What people did after clicking') !== null).toBe(shows !== null)
        }
    )

    it('lists the sessions once link tracking turns on', async () => {
        renderTab(TRACKING_OFF, true)
        await screen.findByText('Link tracking is off')
        expect(sessionsDateFroms).toEqual([])

        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: true })
        await screen.findByText(READY)
        expect(sessionsDateFroms).toHaveLength(1)
    })

    it("drops the old period's answers and lists the new period's sessions", async () => {
        renderTab({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: true }, true)
        await userEvent.click(await screen.findByText('Scan sessions'))
        await screen.findByText('They booked a demo.')

        emailImpactLogic({ workflowId: WORKFLOW_ID }).actions.setDays(7)
        await screen.findByText(READY)
        expect(screen.queryByText('They booked a demo.')).toBeNull()
        expect(sessionsDateFroms).toHaveLength(2)
        expect(sessionsDateFroms[1]).not.toEqual(sessionsDateFroms[0])
    })
})
