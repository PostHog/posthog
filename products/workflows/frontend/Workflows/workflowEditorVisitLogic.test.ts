import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowAction } from './hogflows/types'
import { workflowEditorVisitLogic } from './workflowEditorVisitLogic'
import { NEW_WORKFLOW, WorkflowLogicProps, workflowLogic } from './workflowLogic'

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

const SAVED_ID = 'wf-visit-1'
const OTHER_ID = 'wf-visit-2'

const PAGEVIEW_TRIGGER = {
    type: 'event',
    filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }] },
} as const

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
            { start_path: 'blank', template_id: null, entry_source: null, workflow_id: null, status: 'draft' },
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
                last_edit: 'step_added',
                enable_attempted: false,
                seconds_open: 90,
            },
        ])
    })

    it('keeps one visit across the first save, and reports how the draft started', async () => {
        const created = { ...NEW_WORKFLOW, id: SAVED_ID }
        useMocks({
            post: { '/api/environments/:team_id/hog_flows/': created },
            get: {
                '/api/projects/:team_id/hog_flow_templates/tpl-1/': { ...created, id: 'tpl-1', name: 'Welcome' },
                [`/api/environments/:team_id/hog_flows/${SAVED_ID}/`]: created,
            },
        })
        const draftProps = { id: 'new', templateId: 'tpl-1' }
        const draftVisit = await openEditor(draftProps)

        await expectLogic(workflowLogic(draftProps), () => {
            workflowLogic(draftProps).actions.submitWorkflow()
        }).toDispatchActions(['saveWorkflowSuccess'])
        draftVisit.unmount()
        const savedVisit = await openEditor({ id: SAVED_ID })
        savedVisit.unmount()

        expect(captured('workflow draft created')).toEqual([
            { workflow_id: SAVED_ID, entry_source: null, start_path: 'template', template_id: 'tpl-1' },
        ])
        expect(captured('workflow editor opened')).toHaveLength(1)
        expect(captured('workflow editor left')).toEqual([
            expect.objectContaining({
                start_path: 'template',
                template_id: 'tpl-1',
                workflow_id: SAVED_ID,
                ever_saved: true,
                last_edit: 'saved',
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

    it('starts a fresh visit when the saved workflow is not the next one opened', async () => {
        const created = { ...NEW_WORKFLOW, id: SAVED_ID }
        useMocks({
            post: { '/api/environments/:team_id/hog_flows/': created },
            get: {
                [`/api/environments/:team_id/hog_flows/${SAVED_ID}/`]: created,
                [`/api/environments/:team_id/hog_flows/${OTHER_ID}/`]: { ...created, id: OTHER_ID },
            },
        })
        const draftProps = { id: 'new' }
        const draftVisit = await openEditor(draftProps)
        await expectLogic(workflowLogic(draftProps), () => {
            workflowLogic(draftProps).actions.submitWorkflow()
        }).toDispatchActions(['saveWorkflowSuccess'])
        draftVisit.unmount()

        ;(await openEditor({ id: OTHER_ID })).unmount()
        ;(await openEditor({ id: SAVED_ID })).unmount()

        expect(captured('workflow editor opened').map(({ workflow_id }) => workflow_id)).toEqual([
            null,
            OTHER_ID,
            SAVED_ID,
        ])
    })

    it('reports a moved step as the last edit when the save after it fails', async () => {
        const draft = {
            ...NEW_WORKFLOW,
            id: SAVED_ID,
            actions: [...NEW_WORKFLOW.actions, delayStep('wait_valid', { delay_duration: '10m' })],
        }
        useMocks({
            get: { [`/api/environments/:team_id/hog_flows/${SAVED_ID}/`]: draft },
            patch: { [`/api/environments/:team_id/hog_flows/${SAVED_ID}/`]: () => [500, {}] },
        })
        const props = { id: SAVED_ID }
        const visit = await openEditor(props)

        workflowLogic(props).actions.setWorkflowValues({
            edges: [
                { from: 'trigger_node', to: 'wait_valid', type: 'continue' },
                { from: 'wait_valid', to: 'exit_node', type: 'continue' },
            ],
        })
        await expectLogic(workflowLogic(props), () => {
            workflowLogic(props).actions.submitWorkflow()
        }).toDispatchActions(['saveWorkflowFailure'])
        visit.unmount()

        expect(captured('workflow editor left')).toEqual([expect.objectContaining({ last_edit: 'step_edited' })])
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
