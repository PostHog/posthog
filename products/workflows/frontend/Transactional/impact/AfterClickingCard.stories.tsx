import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
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
const REASONS = [
    'They opened the pricing page from the email, compared the two plans and started a trial.',
    'They landed on the invoice page, looked for a download button for a while and left without finding it.',
    'They read the changelog entry the email linked to, then closed the tab.',
]
const FINISHED = scanRequest('completed', (index) =>
    index < 3
        ? {
              state: 'succeeded',
              scanner_result: {
                  model_output: { verdict: ['yes', 'no', 'inconclusive'][index], reasoning: REASONS[index] },
                  signals_count: 0,
              },
          }
        : { state: 'skipped', scan_outcome: 'skipped_limit' }
)
const AI_ANALYSIS_NOT_ALLOWED_DETAIL =
    'Your organization needs to allow AI analysis before you run a Replay Vision scan.'
const AI_ANALYSIS_NOT_ALLOWED: [number, unknown] = [
    400,
    { type: 'validation_error', code: 'ai_data_processing_not_approved', detail: AI_ANALYSIS_NOT_ALLOWED_DETAIL },
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

async function scan(canvasElement: HTMLElement, shows: RegExp | string): Promise<void> {
    const canvas = within(canvasElement)
    await userEvent.click(await canvas.findByText('Scan sessions'))
    await canvas.findByText(shows)
}

export const Ready: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: SESSIONS },
    parameters: { testOptions: { waitForSelector: '[data-attr="email-impact-scan"]' } },
}

export const Scanning: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: SESSIONS },
    play: ({ canvasElement }) => scan(canvasElement, /^5 of 12\ssessions scanned$/),
}

export const Answers: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: SESSIONS, scan: [202, FINISHED] },
    play: async ({ canvasElement }) => {
        await scan(canvasElement, /^No answer for 9\ssessions\.$/)
        await within(canvasElement).findByText('Inconclusive')
    },
}

export const NoSessionsYet: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: { sessions: [], has_more: false } },
    parameters: { testOptions: { waitForSelector: 'text=No sessions to scan yet' } },
}

export const ScanError: StoryObj<AfterClickingStoryArgs> = {
    render: Template,
    args: { sessions: SESSIONS, scan: AI_ANALYSIS_NOT_ALLOWED },
    play: ({ canvasElement }) => scan(canvasElement, AI_ANALYSIS_NOT_ALLOWED_DETAIL),
}
