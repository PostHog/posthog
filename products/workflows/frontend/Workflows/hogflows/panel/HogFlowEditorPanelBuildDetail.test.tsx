import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider, getContext } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow } from '../types'
import { HogFlowEditorPanelBuildDetail } from './HogFlowEditorPanelBuildDetail'

const WORKFLOW_ID = 'wf-panel-detail-1'
const SLACK_ACTION_ID = 'action_function_slack1'
const SLACK_INTEGRATION_ID = 7

const LOGIC_PROPS: WorkflowLogicProps = { id: WORKFLOW_ID }

// Mirrors the real template-slack schema: an integration input, a dependent
// integration_field, and inputs with defaults that the panel seeds on mount.
const SLACK_TEMPLATE = {
    id: 'template-slack',
    name: 'Slack',
    description: 'Sends a message to a Slack channel',
    type: 'destination',
    status: 'stable',
    free: true,
    icon_url: '/static/services/slack.png',
    category: ['Customer Success'],
    code_language: 'hog',
    code: 'return event',
    inputs_schema: [
        {
            key: 'slack_workspace',
            type: 'integration',
            integration: 'slack',
            label: 'Slack workspace',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'channel',
            type: 'integration_field',
            integration_key: 'slack_workspace',
            integration_field: 'slack_channel',
            label: 'Channel to post to',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'icon_emoji',
            type: 'string',
            label: 'Emoji icon',
            default: ':hedgehog:',
            required: false,
            secret: false,
            hidden: false,
        },
        {
            key: 'text',
            type: 'string',
            label: 'Plain text message',
            default: "*{person.name}* triggered event: '{event.event}'",
            required: false,
            secret: false,
            hidden: false,
        },
    ],
}

const SLACK_INTEGRATION = {
    id: SLACK_INTEGRATION_ID,
    kind: 'slack',
    display_name: 'Acme Slack',
    icon_url: '',
    config: {},
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
}

const WORKFLOW: HogFlow = {
    id: WORKFLOW_ID,
    name: 'Panel detail test',
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
            id: SLACK_ACTION_ID,
            type: 'function',
            name: 'Slack',
            description: 'Send a Slack message to the user.',
            created_at: 0,
            updated_at: 0,
            config: { template_id: 'template-slack', inputs: {} },
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
        { from: 'trigger_node', to: SLACK_ACTION_ID, type: 'continue' },
        { from: SLACK_ACTION_ID, to: 'exit_node', type: 'continue' },
    ],
    conversion: { window_minutes: null, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
}

describe('HogFlowEditorPanelBuildDetail', () => {
    let wfLogic: ReturnType<typeof workflowLogic.build>
    let edLogic: ReturnType<typeof hogFlowEditorLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': WORKFLOW,
                '/api/projects/:team_id/hog_function_templates/': { results: [SLACK_TEMPLATE], count: 1 },
                '/api/environments/:team_id/integrations': { results: [SLACK_INTEGRATION] },
                '/api/environments/:team_id/integrations/:id/channels': {
                    channels: [],
                    lastRefreshedAt: '2026-05-01T00:00:00.000Z',
                },
                '/api/environments/:team_id/messaging_categories': { results: [] },
            },
        })
        initKeaTests()
        wfLogic = workflowLogic(LOGIC_PROPS)
        wfLogic.mount()
        edLogic = hogFlowEditorLogic(LOGIC_PROPS)
        edLogic.mount()
        await expectLogic(wfLogic).toDispatchActions(['loadWorkflowSuccess', 'loadHogFunctionTemplatesByIdSuccess'])
        // The workflow subscription rebuilds the graph asynchronously (layout pass); wait for the
        // slack node to exist so the panel has a selectedNode to render.
        await waitFor(() => expect(edLogic.values.nodesById[SLACK_ACTION_ID]).toBeTruthy())
    })

    afterEach(() => {
        cleanup()
    })

    const getSlackInputs = (): Record<string, any> => {
        const action = wfLogic.values.workflow.actions.find((a) => a.id === SLACK_ACTION_ID)
        return action && 'inputs' in action.config ? (action.config.inputs ?? {}) : {}
    }

    it('settles a slack step configuration without a workflow write loop', async () => {
        // Regression: the panel renders from the async-rebuilt graph, so its props lag behind
        // writes. Unguarded auto-default effects (integration auto-select, template defaults
        // seeding) used to re-fire on every "still empty" render, dispatching workflow writes
        // in a loop until React crashed with error #185 (maximum update depth exceeded).
        let workflowWrites = 0
        const { store } = getContext()
        const realDispatch = store.dispatch.bind(store)
        const dispatchSpy = ((action: any) => {
            if (typeof action?.type === 'string' && action.type.startsWith('set workflow values')) {
                workflowWrites += 1
            }
            return realDispatch(action)
        }) as typeof store.dispatch
        store.dispatch = dispatchSpy

        act(() => {
            edLogic.actions.setSelectedNodeId(SLACK_ACTION_ID)
        })

        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
                    <BindLogic logic={hogFlowEditorLogic} props={LOGIC_PROPS}>
                        <HogFlowEditorPanelBuildDetail />
                    </BindLogic>
                </BindLogic>
            </Provider>
        )

        // Template defaults get seeded into the action's inputs...
        await waitFor(() => expect(getSlackInputs().icon_emoji).toEqual({ value: ':hedgehog:' }))
        // ...and the first available slack integration is auto-selected exactly once.
        await waitFor(() => expect(getSlackInputs().slack_workspace).toEqual({ value: SLACK_INTEGRATION_ID }))
        await waitFor(() => expect(screen.getByText('Acme Slack')).toBeInTheDocument())

        // Seeding (1) + auto-select's field-clear and value-set (2) plus graph round-trips.
        // A loop produces hundreds of writes before React throws; leave generous headroom.
        expect(workflowWrites).toBeLessThan(10)
    })
})
