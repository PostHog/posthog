import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { hogFlowEditorLogic } from './hogflows/hogFlowEditorLogic'
import type { HogFlow, HogFlowAction } from './hogflows/types'
import { workflowEditorVisitLogic } from './workflowEditorVisitLogic'
import { NEW_WORKFLOW, TriggerAction, WorkflowLogicProps, workflowLogic } from './workflowLogic'

const delayStep = (id: string, config: Record<string, unknown>): HogFlowAction =>
    ({
        id,
        type: 'delay',
        name: 'Wait',
        description: '',
        created_at: 0,
        updated_at: 0,
        config,
    }) as HogFlowAction

const branchStep = (id: string): HogFlowAction =>
    ({
        id,
        type: 'conditional_branch',
        name: 'Split',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: { conditions: [{ filters: {} }] },
    }) as HogFlowAction

const slackStep = (id: string): HogFlowAction =>
    ({
        id,
        type: 'function',
        name: 'Slack',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: { template_id: 'template-slack', inputs: {} },
    }) as HogFlowAction

const SAVED_ID = 'wf-visit-1'

const PAGEVIEW_TRIGGER: TriggerAction['config'] = {
    type: 'event',
    filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }] },
}

describe('workflowEditorVisitLogic', () => {
    let captureSpy: jest.SpyInstance

    const captured = (event: string): Record<string, unknown>[] =>
        captureSpy.mock.calls.filter(([name]) => name === event).map(([, properties]) => properties)

    const openEditor = async (
        props: WorkflowLogicProps
    ): Promise<ReturnType<typeof workflowEditorVisitLogic.build>> => {
        const editor = workflowLogic(props)
        editor.mount()
        await expectLogic(editor).toDispatchActions(['loadWorkflowSuccess'])
        const visit = workflowEditorVisitLogic(props)
        visit.mount()
        return visit
    }

    const addStep = (props: WorkflowLogicProps, step: HogFlowAction): void => {
        const editor = workflowLogic(props)
        editor.actions.setWorkflowValues({ actions: [...editor.values.workflow.actions, step] })
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture')
    })

    afterEach(() => {
        captureSpy.mockRestore()
        jest.useRealTimers()
    })

    it('reports how far a blank workflow got when the person leaves without saving', async () => {
        jest.useFakeTimers({ now: new Date('2026-10-18T10:00:00Z'), doNotFake: ['nextTick', 'setImmediate'] })
        const props = { id: 'new' }
        const visit = await openEditor(props)

        expect(captured('workflow editor opened')).toEqual([
            {
                start_path: 'blank',
                template_id: null,
                entry_source: null,
                workflow_id: null,
                status: 'draft',
                editor_layout: 'graph',
            },
        ])

        workflowLogic(props).actions.setWorkflowActionConfig('trigger_node', PAGEVIEW_TRIGGER)
        addStep(props, delayStep('wait_valid', { delay_duration: '10m' }))
        addStep(props, delayStep('wait_unset', {}))
        jest.setSystemTime(new Date('2026-10-18T10:01:30Z'))
        visit.unmount()

        expect(captured('workflow editor left')).toEqual([
            {
                start_path: 'blank',
                template_id: null,
                entry_source: null,
                workflow_id: null,
                status: 'draft',
                ever_saved: false,
                trigger_type: 'event',
                trigger_valid: true,
                step_count: 2,
                invalid_step_count: 1,
                invalid_step_types: ['delay'],
                step_types: { delay: 2 },
                branch_count: 0,
                editor_layout: 'graph',
                layout_switch_count: 0,
                last_edit: 'step_added',
                last_added_step_type: 'delay',
                enable_attempted: false,
                seconds_open: 90,
            },
        ])
    })

    it('ends the visit to a new workflow at its first save, under the saved workflow', async () => {
        const created = { ...NEW_WORKFLOW, id: SAVED_ID }
        useMocks({
            post: { '/api/environments/:team_id/hog_flows/': created },
            get: { '/api/projects/:team_id/hog_flow_templates/tpl-1/': { ...created, id: 'tpl-1', name: 'Welcome' } },
        })
        const props = { id: 'new', templateId: 'tpl-1' }
        const visit = await openEditor(props)

        await expectLogic(workflowLogic(props), () => {
            workflowLogic(props).actions.submitWorkflow()
        }).toDispatchActions(['saveWorkflowSuccess'])
        visit.unmount()

        expect(captured('workflow draft created')).toEqual([
            { workflow_id: SAVED_ID, entry_source: null, start_path: 'template', template_id: 'tpl-1' },
        ])
        expect(captured('workflow editor left')).toEqual([
            expect.objectContaining({
                start_path: 'template',
                template_id: 'tpl-1',
                workflow_id: SAVED_ID,
                ever_saved: true,
            }),
        ])
    })

    it('reports the leave by beacon when the tab closes, and starts a new visit when the browser restores the page', async () => {
        const visit = await openEditor({ id: 'new' })

        window.dispatchEvent(new Event('pagehide'))
        window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))
        visit.unmount()

        expect(captured('workflow editor opened')).toHaveLength(2)
        const leaves = captureSpy.mock.calls.filter(([name]) => name === 'workflow editor left')
        expect(leaves).toEqual([
            ['workflow editor left', expect.objectContaining({ start_path: 'blank' }), { transport: 'sendBeacon' }],
            ['workflow editor left', expect.objectContaining({ start_path: 'blank' }), undefined],
        ])
    })

    it('reports moving a step as a step edit', async () => {
        const draft = {
            ...NEW_WORKFLOW,
            id: SAVED_ID,
            actions: [...NEW_WORKFLOW.actions, delayStep('wait_valid', { delay_duration: '10m' })],
        }
        useMocks({ get: { [`/api/environments/:team_id/hog_flows/${SAVED_ID}/`]: draft } })
        const props = { id: SAVED_ID }
        const visit = await openEditor(props)

        workflowLogic(props).actions.setWorkflowValues({
            edges: [
                { from: 'trigger_node', to: 'wait_valid', type: 'continue' },
                { from: 'wait_valid', to: 'exit_node', type: 'continue' },
            ],
        })
        visit.unmount()

        expect(captured('workflow editor left')).toEqual([expect.objectContaining({ last_edit: 'step_edited' })])
    })

    it('reports the layout a person lands in and each switch they make', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_LINEAR_VIEW], {
            [FEATURE_FLAGS.WORKFLOWS_LINEAR_VIEW]: true,
        })
        useMocks({ get: { [`/api/environments/:team_id/hog_flows/${SAVED_ID}/`]: { ...NEW_WORKFLOW, id: SAVED_ID } } })
        const props = { id: SAVED_ID }
        const visit = await openEditor(props)

        hogFlowEditorLogic(props).actions.switchEditorLayout('advanced')
        hogFlowEditorLogic(props).actions.switchEditorLayout('simple')
        visit.unmount()

        expect(captured('workflow editor opened')).toEqual([expect.objectContaining({ editor_layout: 'list' })])
        expect(captured('workflow editor left')).toEqual([
            expect.objectContaining({ editor_layout: 'list', layout_switch_count: 2 }),
        ])
    })

    it('reports which kinds of steps the workflow holds and where it branches', async () => {
        const branched = {
            ...NEW_WORKFLOW,
            id: SAVED_ID,
            actions: [...NEW_WORKFLOW.actions, branchStep('split'), delayStep('wait_valid', { delay_duration: '10m' })],
            edges: [
                { from: 'trigger_node', to: 'split', type: 'continue' },
                { from: 'split', to: 'wait_valid', type: 'branch', index: 0 },
                { from: 'split', to: 'exit_node', type: 'continue' },
                { from: 'wait_valid', to: 'exit_node', type: 'continue' },
            ],
        } as HogFlow
        useMocks({ get: { [`/api/environments/:team_id/hog_flows/${SAVED_ID}/`]: branched } })
        const props = { id: SAVED_ID }
        const visit = await openEditor(props)

        addStep(props, slackStep('notify'))
        visit.unmount()

        expect(captured('workflow editor left')).toEqual([
            expect.objectContaining({
                step_types: { conditional_branch: 1, delay: 1, 'function:template-slack': 1 },
                branch_count: 1,
                last_added_step_type: 'function:template-slack',
            }),
        ])
    })

    it('reports which steps block a draft from going live', async () => {
        const draft = {
            ...NEW_WORKFLOW,
            id: SAVED_ID,
            actions: [...NEW_WORKFLOW.actions, delayStep('wait_unset', {})],
        }
        useMocks({ get: { [`/api/environments/:team_id/hog_flows/${SAVED_ID}/`]: draft } })
        const props = { id: SAVED_ID }
        const visit = await openEditor(props)

        workflowLogic(props).actions.saveWorkflowPartial({ status: 'active' })
        visit.unmount()

        expect(captured('workflow enable blocked')).toEqual([
            { workflow_id: SAVED_ID, invalid_step_count: 1, invalid_step_types: ['delay'] },
        ])
        expect(captured('workflow editor left')).toEqual([
            expect.objectContaining({ status: 'draft', enable_attempted: true }),
        ])
    })
})
