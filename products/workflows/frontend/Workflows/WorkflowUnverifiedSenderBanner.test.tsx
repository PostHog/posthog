import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import posthog from 'posthog-js'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, IntegrationType } from '~/types'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneHeader } from './WorkflowSceneHeader'
import { WorkflowUnverifiedSenderBanner } from './WorkflowUnverifiedSenderBanner'

const WORKFLOW_ID = 'wf-unverified-sender-1'

const DRAFT_SENDING_FROM_PENDING_DOMAIN: HogFlow = {
    id: WORKFLOW_ID,
    name: 'Welcome',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        {
            id: 'email_node',
            type: 'function_email',
            name: 'Send email',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: {
                template_id: 'template-email',
                inputs: {
                    email: {
                        value: {
                            to: { email: 'recipient@example.com' },
                            from: { integrationId: 42 },
                            subject: 'Hello',
                            html: '<p>Hello</p>',
                        },
                        templating: 'liquid',
                    },
                },
            },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'email_node', type: 'continue' }],
    conversion: { filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    user_access_level: AccessControlLevel.Editor,
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
}

const sender = (verified: boolean): IntegrationType =>
    ({
        id: 42,
        kind: 'email',
        display_name: 'hello@example.dev',
        config: { email: 'hello@example.dev', domain: 'example.dev', verified },
    }) as IntegrationType

const enableButton = (): HTMLElement => screen.getByText('Enable').closest('button')!

describe('WorkflowUnverifiedSenderBanner', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let domainVerified: boolean

    beforeEach(async () => {
        domainVerified = false
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': DRAFT_SENDING_FROM_PENDING_DOMAIN,
                '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
                '/api/projects/:team_id/hog_function_templates/': () => new Promise(() => {}),
                '/api/environments/:team_id/integrations': () => [200, { results: [sender(domainVerified)] }],
            },
            post: {
                '/api/environments/:team_id/integrations/:id/email/verify': () => [
                    200,
                    { status: domainVerified ? 'success' : 'pending', dnsRecords: [] },
                ],
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
            await integrationsLogic.asyncActions.loadIntegrations()
        })
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <WorkflowSceneHeader id={WORKFLOW_ID} />
                    <WorkflowUnverifiedSenderBanner />
                </BindLogic>
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it('blocks enabling until the sender is verified from the banner', async () => {
        expect(enableButton()).toHaveAttribute('aria-disabled', 'true')
        expect(screen.getByText(/hello@example.dev can't send until its domain is verified/)).toBeInTheDocument()

        const capture = jest.spyOn(posthog, 'capture').mockClear()
        domainVerified = true
        act(() => {
            screen.getAllByText('Verify sender')[0].click()
        })

        await waitFor(() => expect(enableButton()).not.toHaveAttribute('aria-disabled', 'true'))
        expect(screen.queryByText(/can't send until its domain is verified/)).not.toBeInTheDocument()
        expect(screen.getByText('Configure email sender')).toBeInTheDocument()
        expect(capture).toHaveBeenCalledWith('workflows verify sender clicked', {
            source: 'workflow_banner',
            workflow_id: WORKFLOW_ID,
        })
    })
})
