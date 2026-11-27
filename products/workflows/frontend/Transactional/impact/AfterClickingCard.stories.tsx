import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { BindLogic, useActions } from 'kea'
import { useLayoutEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { useStorybookMocks } from '~/mocks/browser'

import type { TransactionalEmailImpactSessionsApi } from 'products/messaging/frontend/generated/api.schemas'
import type {
    ObservationRequestApi,
    ObservationRequestSessionApi,
} from 'products/replay_vision/frontend/generated/api.schemas'

import { AfterClickingCard } from './AfterClickingCard'
import { emailImpactLogic } from './emailImpactLogic'

const WORKFLOW_ID = '0190a1b2-0000-7000-8000-0000000000f2'
const TEAM = { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: true }

const SESSIONS: TransactionalEmailImpactSessionsApi = {
    sessions: Array.from({ length: 12 }, (_, index) => ({
        session_id: `session-${index}`,
        message_id: `message-${index}`,
        first_pageview_at: '2026-11-26T10:00:00Z',
    })),
    has_more: false,
}

function scanRequest(
    status: 'running' | 'completed',
    session: (index: number) => Partial<ObservationRequestSessionApi>
): ObservationRequestApi {
    return {
        id: '01a21d51-012a-7d3d-a576-b38b7254d78a',
        status,
        scanner_id: 'scanner-1',
        reference: `workflows-email:${WORKFLOW_ID}`,
        created_at: '2026-11-27T10:00:00Z',
        sessions: SESSIONS.sessions.map(({ session_id }, index) => ({
            session_id,
            scan_outcome: 'started',
            state: 'running',
            observation_id: null,
            scanner_result: null,
            ...session(index),
        })),
    }
}

const SCANNING = scanRequest('running', (index) =>
    index < 5 ? { state: 'succeeded', observation_id: `01a21d52-3c4d-7e5f-8a9b-0c1d2e3f4a5${index}` } : {}
)
const CREDITS_USED_UP = scanRequest('completed', () => ({ state: 'skipped', scan_outcome: 'skipped_quota' }))
const AI_ANALYSIS_NOT_ALLOWED: [number, unknown] = [
    400,
    {
        type: 'validation_error',
        code: 'ai_data_processing_not_approved',
        detail: 'Your organization needs to allow AI analysis before you run a Replay Vision scan.',
    },
]

const meta: Meta = {
    title: 'Products/Workflows/AfterClickingCard',
    component: AfterClickingCard,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_EMAIL_IMPACT_REPLAY_VISION],
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

interface AfterClickingStoryArgs {
    sessions: TransactionalEmailImpactSessionsApi
    scan?: [number, unknown]
}

const Template: StoryFn<AfterClickingStoryArgs> = ({ sessions, scan = [202, SCANNING] }) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/transactional_email_log/impact/': () => [404, {}],
            '/api/projects/:team_id/transactional_email_log/impact_sessions/': () => [200, sessions],
            '/api/projects/:team_id/vision/requests/:id/': () => [200, scan[1]],
        },
        post: { '/api/projects/:team_id/vision/requests/': () => scan },
    })
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    const [ready, setReady] = useState(false)
    useLayoutEffect(() => {
        loadCurrentTeamSuccess(TEAM)
        setReady(true)
    }, [loadCurrentTeamSuccess])

    return ready ? (
        <BindLogic logic={emailImpactLogic} props={{ workflowId: WORKFLOW_ID }}>
            <AfterClickingCard />
        </BindLogic>
    ) : (
        <></>
    )
}

async function askWhereStuck(canvasElement: HTMLElement, shows: string): Promise<void> {
    const canvas = within(canvasElement)
    await userEvent.click(await canvas.findByText('Where do people get stuck after clicking?'))
    await waitFor(() => canvas.getByText((_, element) => element?.tagName === 'SPAN' && element.textContent === shows))
}

export const Questions: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: SESSIONS },
    parameters: { testOptions: { waitForSelector: '[data-attr="email-impact-question-stuck"]' } },
}

export const Scanning: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: SESSIONS },
    play: ({ canvasElement }) => askWhereStuck(canvasElement, '5 of 12 sessions scanned'),
}

export const NoSessionsYet: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: { sessions: [], has_more: false } },
    parameters: { testOptions: { waitForSelector: 'text=No sessions yet' } },
}

export const AIAnalysisNotAllowed: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: SESSIONS, scan: AI_ANALYSIS_NOT_ALLOWED },
    play: ({ canvasElement }) => askWhereStuck(canvasElement, 'AI analysis is off for this organization'),
}

export const CreditsUsedUp: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: SESSIONS, scan: [202, CREDITS_USED_UP] },
    play: ({ canvasElement }) => askWhereStuck(canvasElement, 'Replay vision credits are used up'),
}
