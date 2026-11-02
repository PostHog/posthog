import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow } from '../../types'
import { tileCanvasLogic } from './tileCanvasLogic'
import { TileCanvasMeasureLayer } from './TileCanvasMeasureLayer'

jest.mock('lib/components/AppMetrics/appMetricsLogic', () => ({
    ...jest.requireActual('lib/components/AppMetrics/appMetricsLogic'),
    loadAppMetricsTotals: () => new Promise(() => {}),
}))

const WORKFLOW_ID = 'wf-measure-1'

const WORKFLOW = {
    id: WORKFLOW_ID,
    name: 'Measure test',
    version: 1,
    status: 'draft',
    team_id: 1,
    exit_condition: 'exit_only_at_end',
    trigger: { type: 'event', filters: {} },
    actions: [
        { id: 'trigger_node', type: 'trigger', name: 'Trigger', config: { type: 'event', filters: {} } },
        { id: 'sync', type: 'function', name: 'Sync', config: { template_id: 'template-hubspot', inputs: {} } },
        { id: 'exit_node', type: 'exit', name: 'Exit', config: { reason: '' } },
    ],
    edges: [
        { from: 'trigger_node', to: 'sync', type: 'continue' },
        { from: 'sync', to: 'exit_node', type: 'continue' },
    ],
    created_at: '2026-10-01T00:00:00.000Z',
    updated_at: '2026-10-01T00:00:00.000Z',
} as unknown as HogFlow

describe('TileCanvasMeasureLayer', () => {
    let flowLogic: ReturnType<typeof workflowLogic.build>
    let canvasLogic: ReturnType<typeof tileCanvasLogic.build>

    beforeEach(async () => {
        Object.defineProperty(document, 'fonts', { value: { ready: new Promise(() => {}) }, configurable: true })
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': WORKFLOW,
                '/api/projects/:team_id/hog_function_templates/': {
                    results: [{ id: 'template-hubspot', name: 'HubSpot', type: 'destination' }],
                    count: 1,
                },
            },
        })
        initKeaTests()
        flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await act(async () => {
            await flowLogic.asyncActions.loadWorkflow()
        })
        canvasLogic = tileCanvasLogic({ id: WORKFLOW_ID })
        canvasLogic.mount()
    })

    afterEach(() => cleanup())

    const renderLayer = (): HTMLElement =>
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <BindLogic logic={tileCanvasLogic} props={{ id: WORKFLOW_ID }}>
                        <TileCanvasMeasureLayer />
                    </BindLogic>
                </BindLogic>
            </Provider>
        ).container

    it('measures the tiles again once template names change their captions', async () => {
        const container = renderLayer()
        await expectLogic(canvasLogic).toDispatchActions([
            'setMeasuredSizes',
            flowLogic.actionTypes.loadHogFunctionTemplatesByIdSuccess,
            'setMeasuredSizes',
        ])
        expect(container).toHaveTextContent('HubSpot')
    })

    it('measures only the step that changed', async () => {
        renderLayer()
        await expectLogic(canvasLogic).toDispatchActions([
            'setMeasuredSizes',
            flowLogic.actionTypes.loadHogFunctionTemplatesByIdSuccess,
            'setMeasuredSizes',
        ])
        const sync = flowLogic.values.workflow.actions.find((action) => action.id === 'sync')!
        const measuredIds = new Set<string | undefined>()
        const measure = jest
            .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
            .mockImplementation(function (this: HTMLElement) {
                measuredIds.add(this.closest<HTMLElement>('[data-measure-id]')?.dataset.measureId)
                return new DOMRect()
            })

        act(() => flowLogic.actions.setWorkflowAction('sync', { ...sync, name: 'Sync contacts' }))

        await expectLogic(canvasLogic).toDispatchActions(['setMeasuredSizes'])
        measure.mockRestore()
        expect([...measuredIds]).toEqual(['sync'])
        expect(Object.keys(canvasLogic.values.measuredSizes ?? {})).toEqual(['trigger_node', 'sync', 'exit_node'])
    })
})
