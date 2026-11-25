import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { optOutCategoriesLogic } from '../../../OptOuts/optOutCategoriesLogic'
import { workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow } from '../types'
import { HogFlowEditorPanelBuildDetail } from './HogFlowEditorPanelBuildDetail'

const WORKFLOW_ID = 'wf-transactional-category'
const EMAIL_NODE_ID = 'transactional_email'

const transactionalEmailWorkflow = (
    messageCategoryId: string | null,
    messageCategoryType: 'marketing' | 'transactional' = 'transactional'
): HogFlow => ({
    id: WORKFLOW_ID,
    name: 'Usage spike detected',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'api' },
        } as HogFlow['actions'][number],
        {
            id: EMAIL_NODE_ID,
            type: 'function_email',
            name: 'Usage spike detected',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: {
                template_id: 'template-email',
                message_category_id: messageCategoryId,
                message_category_type: messageCategoryType,
                inputs: {
                    email: {
                        templating: 'liquid',
                        value: {
                            to: { email: '{{ event.properties.to | raw }}' },
                            from: { integrationId: 42 },
                            subject: 'Your usage spiked',
                            text: 'Usage spiked',
                        },
                    },
                },
            },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [
        { from: 'trigger_node', to: EMAIL_NODE_ID, type: 'continue' },
        { from: EMAIL_NODE_ID, to: 'exit_node', type: 'continue' },
    ],
    conversion: { filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'active',
    team_id: 1,
    trigger: { type: 'api' } as HogFlow['trigger'],
    created_at: '2026-11-01T00:00:00.000Z',
    updated_at: '2026-11-01T00:00:00.000Z',
})

const categories = [
    { id: 'cat-newsletter', key: 'newsletter', name: 'Newsletter', category_type: 'marketing' },
    { id: 'cat-billing', key: 'billing', name: 'Billing', category_type: 'transactional' },
]

const emailStepMocks = (
    messageCategoryId: string | null,
    messageCategoryType: 'marketing' | 'transactional' = 'transactional'
): Parameters<typeof useMocks>[0] => ({
    get: {
        '/api/environments/:team_id/hog_flows/:id/': transactionalEmailWorkflow(messageCategoryId, messageCategoryType),
        '/api/projects/:team_id/hog_function_templates/': () => new Promise(() => {}),
        '/api/environments/:team_id/messaging_categories/': { results: categories, count: 2, next: null },
    },
})

async function renderEmailStep(): Promise<ReturnType<typeof render>> {
    initKeaTests()
    const props = { id: WORKFLOW_ID }
    logic = workflowLogic(props)
    logic.mount()
    await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
    router.actions.push(urls.workflow(WORKFLOW_ID, 'workflow'), { node: EMAIL_NODE_ID })
    hogFlowEditorLogic(props).mount()
    await expectLogic(optOutCategoriesLogic()).toDispatchActions(['loadCategoriesSuccess'])

    return render(
        <Provider>
            <BindLogic logic={workflowLogic} props={props}>
                <BindLogic logic={hogFlowEditorLogic} props={props}>
                    <HogFlowEditorPanelBuildDetail />
                </BindLogic>
            </BindLogic>
        </Provider>
    )
}

let logic: ReturnType<typeof workflowLogic.build>

describe('HogFlowEditorPanelBuildDetail', () => {
    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it.each([
        ['names the type of a transactional step saved without a category', null, 'Transactional, no category'],
        ['shows the chosen category of a transactional step', 'cat-billing', 'Billing'],
    ])('message category: %s', async (_, messageCategoryId, shown) => {
        useMocks(emailStepMocks(messageCategoryId))
        await renderEmailStep()

        expect(screen.getByText('Message category')).toBeInTheDocument()
        expect(screen.getByText(shown)).toBeInTheDocument()
        expect(screen.queryByText('Select message type')).not.toBeInTheDocument()
    })

    it('offers a marketing email step no transactional category', async () => {
        useMocks(emailStepMocks('cat-newsletter', 'marketing'))
        await renderEmailStep()

        fireEvent.click(screen.getByText('Newsletter'))

        expect(screen.getAllByText('Newsletter')).toHaveLength(2)
        expect(screen.queryByText('Billing')).not.toBeInTheDocument()
    })

    it('shows the run link tag hint only while tracking is on', async () => {
        useMocks(emailStepMocks('cat-billing'))
        const { container } = await renderEmailStep()
        expect(screen.getByText(/are connected to the sessions they start/)).toBeInTheDocument()

        fireEvent.click(container.querySelector('[data-attr="workflow-email-tracking-toggle"]') as HTMLElement)

        expect(screen.queryByText(/are connected to the sessions they start/)).not.toBeInTheDocument()
        expect(screen.queryByText('Turn it off in settings')).not.toBeInTheDocument()
    })
})
