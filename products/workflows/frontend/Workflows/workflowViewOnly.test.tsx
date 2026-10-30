import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { ViewOnlyArea } from './hogflows/panel/ViewOnlyArea'
import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { WorkflowViewOnlyBanner } from './WorkflowViewOnlyBanner'

const WORKFLOW_ID = 'wf-view-only-1'

const VIEWER_WORKFLOW: HogFlow = {
    id: WORKFLOW_ID,
    name: 'Shared onboarding',
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
    ],
    edges: [],
    conversion: { filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
    user_access_level: AccessControlLevel.Viewer,
}

function setWorkflowResourceAccess(level: AccessControlLevel): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        resource_access_control: {
            ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
            [AccessControlResourceType.Workflow]: level,
        },
    } as AppContext
}

function renderForViewer(children: JSX.Element): void {
    render(
        <Provider>
            <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                {children}
            </BindLogic>
        </Provider>
    )
}

describe('view-only workflow', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': VIEWER_WORKFLOW,
                '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
        })
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it('lets a viewer open nested sections of a step', () => {
        renderForViewer(
            <ViewOnlyArea>
                <LemonCollapse
                    panels={[{ key: 'ios', header: 'iOS options', content: <input aria-label="Sound" /> }]}
                />
            </ViewOnlyArea>
        )

        const header = screen.getByText('iOS options').closest('button')
        expect(header).toBeEnabled()
        fireEvent.click(header!)

        expect(screen.getByLabelText('Sound')).toBeInTheDocument()
    })

    it.each([
        [AccessControlLevel.Editor, true],
        [AccessControlLevel.Viewer, false],
    ])('offers Duplicate to a viewer with %s access to workflows: %s', (resourceLevel, offersDuplicate) => {
        setWorkflowResourceAccess(resourceLevel)

        renderForViewer(<WorkflowViewOnlyBanner id={WORKFLOW_ID} />)

        expect(screen.getByText(/You can view this workflow but not edit it/)).toBeInTheDocument()
        expect(document.querySelector('[data-attr="workflow-view-only-duplicate"]') !== null).toBe(offersDuplicate)
    })
})
