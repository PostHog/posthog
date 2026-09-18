import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { HogFlow } from './hogflows/types'
import { WorkflowDraftBanner } from './WorkflowDraftBanner'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-draft-banner-1'
const MESSAGE = 'This workflow is a draft.'

const workflowWithStatus = (status: HogFlow['status']): HogFlow =>
    ({
        id: WORKFLOW_ID,
        name: 'Draft banner test',
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
                id: 'exit_node',
                type: 'exit',
                name: 'Exit',
                description: '',
                created_at: 0,
                updated_at: 0,
                config: { reason: 'Default exit' },
            },
        ],
        edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
        conversion: { window_minutes: null, filters: [] },
        exit_condition: 'exit_only_at_end',
        version: 1,
        status,
        team_id: 1,
        trigger: { type: 'event', filters: {} },
        created_at: '2026-05-01T00:00:00.000Z',
        updated_at: '2026-05-01T00:00:00.000Z',
        user_access_level: AccessControlLevel.Editor,
    }) as HogFlow

describe('WorkflowDraftBanner', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let status: HogFlow['status']

    beforeEach(() => {
        status = 'draft'
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [200, workflowWithStatus(status)],
                '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    const mountBanner = async (id: string = WORKFLOW_ID): Promise<void> => {
        logic = workflowLogic({ id })
        logic.mount()
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
        })
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id }}>
                    <WorkflowDraftBanner message={MESSAGE} />
                </BindLogic>
            </Provider>
        )
    }

    // The whole point of the banner: a live workflow must not be told it never runs, and a draft
    // must be, on every surface a person debugs from.
    it.each([
        ['draft', true],
        ['active', false],
    ] as [HogFlow['status'], boolean][])('shows the notice on a %s workflow: %s', async (workflowStatus, expected) => {
        status = workflowStatus
        await mountBanner()

        expect(screen.queryByText(MESSAGE) !== null).toBe(expected)
    })

    // An unsaved workflow also reads as a draft, and enabling one creates a live workflow instead
    // of changing it. The template editor runs on this same route.
    it('stays out of the way of a workflow that does not exist yet', async () => {
        await mountBanner('new')

        expect(screen.queryByText(MESSAGE)).toBeNull()
    })

    it('holds the enable action until the in-progress edits are saved', async () => {
        await mountBanner()

        // LemonBanner renders the action twice, once per width; either copy tells the same story.
        const enable = (): Element | null => document.querySelector('[data-attr="workflow-draft-banner-enable"]')
        expect(enable()).not.toHaveAttribute('aria-disabled', 'true')

        act(() => {
            logic.actions.setWorkflowValue('name', 'Still typing')
        })

        expect(enable()).toHaveAttribute('aria-disabled', 'true')
    })
})
