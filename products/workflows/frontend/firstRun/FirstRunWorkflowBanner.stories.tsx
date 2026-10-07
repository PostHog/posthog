import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import welcomeEmailSequence from '../../backend/templates/welcome_email_sequence_template.json'
import type { HogFlow } from '../Workflows/hogflows/types'
import { workflowLogic } from '../Workflows/workflowLogic'
import { OWN_SENDER } from './firstRunStoryFixtures'
import { FirstRunWorkflowBanner } from './FirstRunWorkflowBanner'
import { rememberFirstRunWorkflow } from './firstRunWorkflowStorage'
import { withFirstRunSender } from './withFirstRunSender'

const FIRST_RUN_WORKFLOW_ID = 'storybook-first-run-workflow'

function firstRunWorkflow(status: HogFlow['status']): HogFlow {
    const { id, scope, image_url, ...content } = welcomeEmailSequence as unknown as HogFlow & {
        scope: string
        image_url: string
    }
    return {
        ...content,
        actions: withFirstRunSender(content.actions, { id: OWN_SENDER.id! }),
        id: FIRST_RUN_WORKFLOW_ID,
        status,
        version: 1,
        created_at: '2026-10-05T12:00:00.000Z',
        updated_at: '2026-10-05T12:00:00.000Z',
    } as HogFlow
}

function workflowWithStatus(status: HogFlow['status']): Parameters<typeof mswDecorator>[0] {
    return {
        get: {
            '/api/environments/:team_id/hog_flows/:id/': () => [200, firstRunWorkflow(status)],
            '/api/projects/:team_id/hog_flow_templates/': { count: 0, results: [] },
            '/api/environments/:team_id/messaging_categories': { count: 0, results: [] },
            '/api/projects/:team_id/integrations/': toPaginatedResponse([OWN_SENDER]),
        },
        patch: {
            '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => [
                200,
                { ...firstRunWorkflow(status), ...((await request.json()) as Partial<HogFlow>) },
            ],
        },
    }
}

const meta: Meta = {
    component: App,
    title: 'Products/Workflows/First run workflow banner',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-05',
        pageUrl: urls.workflow(FIRST_RUN_WORKFLOW_ID, 'workflow'),
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN],
        testOptions: { viewport: { width: 1440, height: 900 }, waitForLoadersToDisappear: true },
    },
    decorators: [
        (Story) => {
            rememberFirstRunWorkflow(FIRST_RUN_WORKFLOW_ID)
            return <Story />
        },
    ],
}
export default meta

type Story = StoryObj<{}>

function NarrowBanner(): JSX.Element {
    return (
        <BindLogic logic={workflowLogic} props={{ id: FIRST_RUN_WORKFLOW_ID }}>
            <div className="w-[520px] p-4">
                <FirstRunWorkflowBanner />
            </div>
        </BindLogic>
    )
}

export const Draft: Story = {
    decorators: [mswDecorator(workflowWithStatus('draft'))],
}

export const Sending: Story = {
    decorators: [mswDecorator(workflowWithStatus('active'))],
}

export const DraftNarrow: Story = {
    render: () => <NarrowBanner />,
    decorators: [mswDecorator(workflowWithStatus('draft'))],
}

export const SendingNarrow: Story = {
    render: () => <NarrowBanner />,
    decorators: [mswDecorator(workflowWithStatus('active'))],
}

export const SendingAsMember: Story = {
    render: function SendingAsMember(): JSX.Element {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Member,
        })
        return <App />
    },
    decorators: [mswDecorator(workflowWithStatus('active'))],
}
