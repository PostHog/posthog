import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { loadAppMetricsTotals } from 'lib/components/AppMetrics/appMetricsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import type { HogFlowActionNode } from '../../types'
import * as tileCanvasLayout from './tileCanvasLayout'
import { tileCanvasLogic } from './tileCanvasLogic'
import { stepCount } from './tileCanvasModel'

jest.mock('lib/components/AppMetrics/appMetricsLogic', () => ({
    ...jest.requireActual('lib/components/AppMetrics/appMetricsLogic'),
    loadAppMetricsTotals: jest.fn(),
}))

const WORKFLOW_ID = 'flow-1'

const step = (id: string, type = 'delay', config: Record<string, unknown> = { delay_duration: '1d' }): object => ({
    id,
    type,
    name: id,
    config,
})

// trigger -> split, whose two paths hold two steps each, both ending at exit
const savedWorkflow = {
    id: WORKFLOW_ID,
    name: 'Onboarding',
    version: 1,
    status: 'active',
    trigger: { type: 'event', filters: {} },
    actions: [
        step('trigger_node', 'trigger', { type: 'event', filters: {} }),
        step('split', 'conditional_branch', { conditions: [{ filters: {} }] }),
        step('pause'),
        step('a2'),
        step('b1'),
        step('b2'),
        step('exit_node', 'exit', { reason: 'Done' }),
    ],
    edges: [
        { from: 'trigger_node', to: 'split', type: 'continue' },
        { from: 'split', to: 'pause', type: 'branch', index: 0 },
        { from: 'pause', to: 'a2', type: 'continue' },
        { from: 'a2', to: 'exit_node', type: 'continue' },
        { from: 'split', to: 'b1', type: 'continue' },
        { from: 'b1', to: 'b2', type: 'continue' },
        { from: 'b2', to: 'exit_node', type: 'continue' },
    ],
    updated_at: '2026-10-01T00:00:00.000Z',
}

async function mountSavedCanvas(): Promise<ReturnType<typeof tileCanvasLogic.build>> {
    initKeaTests()
    const flowLogic = workflowLogic({ id: WORKFLOW_ID })
    flowLogic.mount()
    await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])
    const canvasLogic = tileCanvasLogic({ id: WORKFLOW_ID })
    canvasLogic.mount()
    await expectLogic(canvasLogic).toDispatchActions(['loadStepCountsSuccess'])
    return canvasLogic
}

const totals = (rows: [instanceId: string, metric: string, total: number][]): Record<string, unknown> =>
    Object.fromEntries(
        rows.map(([instanceId, metric, total]) => [
            `${instanceId}_${metric}`,
            { total, breakdowns: [instanceId, metric] },
        ])
    )

describe('tileCanvasLogic', () => {
    let logic: ReturnType<typeof tileCanvasLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': savedWorkflow,
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
    })

    describe('panels', () => {
        beforeEach(() => {
            initKeaTests()
            logic = tileCanvasLogic()
            logic.mount()
        })

        it('opens a panel mode and closes it again from the same command', async () => {
            await expectLogic(logic, () => logic.actions.togglePanel('logs')).toMatchValues({ panelMode: 'logs' })
            await expectLogic(logic, () => logic.actions.togglePanel('logs')).toMatchValues({
                panelMode: null,
                isPanelOpen: false,
            })
        })

        it('keeps the selected step when the panel switches mode', async () => {
            const stepId = logic.values.workflow.actions[0].id
            logic.actions.selectStep(stepId)

            await expectLogic(logic, () => logic.actions.togglePanel('logs')).toMatchValues({
                panelMode: 'logs',
                selectedNodeId: stepId,
            })
        })

        it('leaves history for the build mode of a step picked on the canvas', async () => {
            const stepId = logic.values.workflow.actions[0].id
            await expectLogic(logic, () => logic.actions.togglePanel('history')).toMatchValues({
                panelMode: 'history',
            })

            await expectLogic(logic, () => logic.actions.selectStep(stepId)).toMatchValues({
                panelMode: 'build',
                selectedNodeId: stepId,
            })
        })
    })

    describe('step menu', () => {
        beforeEach(async () => {
            jest.mocked(loadAppMetricsTotals).mockResolvedValue({})
            logic = await mountSavedCanvas()
        })

        it('selects the step under the menu without opening the panel', async () => {
            await expectLogic(logic, () => logic.actions.openStepMenu('b1')).toMatchValues({
                selectedNodeId: 'b1',
                stepMenuActionId: 'b1',
                isPanelOpen: false,
            })
        })

        it('opens the step panel for a step and the path for a stack, from a click or the keyboard', async () => {
            const [stack] = logic.values.visibleGraph.nodes.filter((node) => node.kind === 'stack')

            await expectLogic(logic, () => logic.actions.activateNode('split')).toMatchValues({
                selectedNodeId: 'split',
                isPanelOpen: true,
            })
            await expectLogic(logic, () => logic.actions.activateNode(stack.id)).toMatchValues({
                openPathIds: [stack.id],
            })
        })

        it.each([
            { name: 'clears the step a closed menu picked', panelOpen: false, selected: null },
            { name: 'keeps the step the open panel shows', panelOpen: true, selected: 'b1' },
        ])('$name', async ({ panelOpen, selected }) => {
            if (panelOpen) {
                logic.actions.selectStep('b1')
            }
            logic.actions.openStepMenu('b1')

            await expectLogic(logic, () => logic.actions.closeStepMenu()).toMatchValues({ selectedNodeId: selected })
        })

        it('opens the panel for a step picked on the canvas', async () => {
            await expectLogic(logic, () => logic.actions.selectStep('b1')).toMatchValues({
                selectedNodeId: 'b1',
                isPanelOpen: true,
            })
        })
    })

    describe('typing anywhere', () => {
        let scene: HTMLElement
        let canvas: HTMLElement

        beforeEach(() => {
            initKeaTests()
            logic = tileCanvasLogic()
            logic.mount()
            scene = document.body.appendChild(document.createElement('main'))
            canvas = scene.appendChild(document.createElement('div'))
            canvas.className = 'TileCanvas__flow'
        })

        afterEach(() => {
            document.body.innerHTML = ''
        })

        it.each([
            { name: 'the page itself', place: (): HTMLElement => document.body, opens: true },
            { name: 'the scene that holds the canvas', place: (): HTMLElement => scene, opens: true },
            {
                name: 'the canvas',
                place: (): HTMLElement => canvas.appendChild(document.createElement('div')),
                opens: true,
            },
            {
                name: 'a button in the step panel',
                place: (): HTMLElement => scene.appendChild(document.createElement('button')),
                opens: false,
            },
        ])('opens the command palette from a key typed on $name: $opens', ({ place, opens }) => {
            place().dispatchEvent(new KeyboardEvent('keydown', { key: 'd', bubbles: true }))

            expect(logic.values.commandPaletteQuery).toBe(opens ? 'd' : null)
        })
    })

    describe('placing a step', () => {
        const delayStep = { type: 'delay', name: 'Delay', description: '', config: { delay_duration: '1h' } } as const

        beforeEach(() => {
            initKeaTests()
            logic = tileCanvasLogic()
            logic.mount()
        })

        it.each([
            {
                source: 'palette',
                add: (): void => {
                    logic.actions.openCommandPalette('d')
                    logic.actions.startPlacing(delayStep)
                    logic.actions.placeAt(logic.values.workflow.edges[0])
                },
            },
            {
                source: 'command bar',
                add: (): void => {
                    logic.actions.openCommandPalette()
                    logic.actions.startPlacing(delayStep)
                    logic.actions.placeAt(logic.values.workflow.edges[0])
                },
            },
            {
                source: 'quick add',
                add: (): void => logic.actions.addStepAt(delayStep, logic.values.workflow.edges[0]),
            },
        ])('counts a step added from the $source', ({ source, add }) => {
            const capture = jest.spyOn(posthog, 'capture')

            add()

            expect(capture).toHaveBeenCalledWith('workflows tile canvas step added', { source, step_type: 'delay' })
        })

        it.each(['startMovingNode', 'startCopyingNode'] as const)(
            'drops a pending %s when someone starts adding a step',
            async (startPending) => {
                const editorLogic = hogFlowEditorLogic()
                const pendingNode = { id: 'exit_node', data: logic.values.workflow.actions[1] } as HogFlowActionNode
                editorLogic.actions[startPending](pendingNode)

                await expectLogic(logic, () => logic.actions.startPlacing(delayStep)).toMatchValues({
                    isMovingNode: false,
                    isCopyingNode: false,
                    nodeToBeAdded: delayStep,
                })
            }
        )

        it('forgets a copied step when a click on the canvas stops the copy', async () => {
            const editorLogic = hogFlowEditorLogic()
            editorLogic.actions.startCopyingNode({
                id: 'exit_node',
                data: logic.values.workflow.actions[1],
            } as HogFlowActionNode)

            await expectLogic(logic, () => logic.actions.handlePaneClick()).toMatchValues({
                isCopyingNode: false,
                nodeToBeAdded: null,
                isPlacing: false,
            })
        })
    })

    describe('paths', () => {
        let layoutSpy: jest.SpyInstance

        beforeEach(async () => {
            jest.mocked(loadAppMetricsTotals).mockResolvedValue({})
            logic = await mountSavedCanvas()
            jest.useFakeTimers()
            // The tests hand the canvas its layouts, so a real one must not land in between.
            layoutSpy = jest.spyOn(tileCanvasLayout, 'layoutTileCanvas').mockReturnValue(new Promise(() => {}))
        })

        afterEach(() => {
            jest.useRealTimers()
            layoutSpy.mockRestore()
        })

        const stackSize = { width: 180, height: 90, anchor: { x: 32, y: 32, width: 64, height: 64 } }
        const stackAt = { x: 200, y: 300 }
        const stack = { ...stackAt, width: 180, height: 90, entry: { x: 232, y: 300 } }
        const frame = { x: 40, y: 300, width: 520, height: 260 }
        const framePlace = { ...frame, entry: { x: 300, y: 300 } }
        const layoutWith = (
            positions: Record<string, { x: number; y: number }>,
            frames: Record<string, typeof frame>
        ): tileCanvasLayout.CanvasLayout => ({ positions, edges: {}, frames, width: 600, height: 600 })

        it('opens a path where its stack was on screen', () => {
            const [group] = logic.values.pathGroups
            logic.actions.setMeasuredSizes({ [group.id]: stackSize })
            logic.actions.setLayout(layoutWith({ [group.id]: stackAt }, {}))

            logic.actions.openPath(group.id)
            logic.actions.setLayout(layoutWith({}, { [`frame:${group.id}`]: frame }))

            expect(logic.values.viewportFocus).toEqual({ place: framePlace, anchor: stack, request: 1 })
        })

        it('collapses a path into a stack where its frame was on screen', () => {
            const [group] = logic.values.pathGroups
            logic.actions.setOpenPathIds([group.id])
            logic.actions.setLayout(layoutWith({}, { [`frame:${group.id}`]: frame }))

            logic.actions.collapsePath(group.id)
            jest.advanceTimersByTime(1000)
            logic.actions.setMeasuredSizes({ [group.id]: stackSize })
            logic.actions.setLayout(layoutWith({ [group.id]: stackAt }, {}))

            expect(logic.values.viewportFocus).toEqual({ place: stack, anchor: framePlace, request: 1 })
        })

        it('keeps an opening stack on the canvas, opened once, until the layout that opens it lands', () => {
            const [group] = logic.values.pathGroups
            const drawnIds = (): string[] => logic.values.drawnGraph.nodes.map((node) => node.id)
            logic.actions.setLayout(layoutWith({ [group.id]: stackAt }, {}), logic.values.visibleGraph)

            logic.actions.openPath(group.id)
            const whileLayingOut = drawnIds()
            logic.actions.activateNode(group.id)
            logic.actions.setLayout(layoutWith({}, { [`frame:${group.id}`]: frame }), logic.values.visibleGraph)

            expect(whileLayingOut).toContain(group.id)
            expect(logic.values.openPathIds).toEqual([group.id])
            expect(drawnIds()).not.toContain(group.id)
        })

        it('brings the path of a step picked elsewhere into view', () => {
            const group = logic.values.pathGroups.find((candidate) => candidate.memberIds.includes('a2'))!

            logic.actions.setSelectedNodeId('a2')
            logic.actions.setLayout(layoutWith({}, { [`frame:${group.id}`]: frame }))

            expect(logic.values.viewportFocus).toEqual({ place: framePlace, anchor: null, request: 1 })
        })

        it('collapses every path someone collapses in quick succession', () => {
            const pathIds = logic.values.pathGroups.map((group) => group.id)
            logic.actions.setOpenPathIds(pathIds)

            pathIds.forEach((pathId) => logic.actions.collapsePath(pathId))
            jest.advanceTimersByTime(1000)

            expect(logic.values.openPathIds).toEqual([])
        })
    })

    describe('layout failure', () => {
        beforeEach(async () => {
            jest.mocked(loadAppMetricsTotals).mockResolvedValue({})
            logic = await mountSavedCanvas()
        })

        it('shows why the canvas could not lay out the workflow, and clears it once a layout works', async () => {
            const layout = jest
                .spyOn(tileCanvasLayout, 'layoutTileCanvas')
                .mockRejectedValueOnce(new RangeError('Maximum call stack size exceeded'))
            const size = { width: 300, height: 80 }

            await expectLogic(logic, () =>
                logic.actions.setMeasuredSizes({ trigger_node: size })
            ).toFinishAllListeners()
            expect(logic.values.layoutError).toBe('Maximum call stack size exceeded')

            await expectLogic(logic, () =>
                logic.actions.setMeasuredSizes({ trigger_node: size, split: size })
            ).toFinishAllListeners()
            expect(logic.values.layoutError).toBeNull()
            layout.mockRestore()
        })

        it('keeps a valid canvas when an older layout fails after the sizes went back to it', async () => {
            const size = { width: 300, height: 80 }
            const valid = { trigger_node: size }
            const layout = jest.spyOn(tileCanvasLayout, 'layoutTileCanvas')
            await expectLogic(logic, () => logic.actions.setMeasuredSizes(valid)).toFinishAllListeners()
            let failOlder: (error: Error) => void = () => {}
            layout.mockReturnValueOnce(new Promise((_, reject) => (failOlder = reject)))

            logic.actions.setMeasuredSizes({ trigger_node: size, split: size })
            await new Promise((resolve) => setTimeout(resolve, 20))
            logic.actions.setMeasuredSizes(valid)
            await new Promise((resolve) => setTimeout(resolve, 20))
            failOlder(new RangeError('Maximum call stack size exceeded'))
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.layoutError).toBeNull()
            layout.mockRestore()
        })
    })

    describe('step counts', () => {
        beforeEach(async () => {
            jest.mocked(loadAppMetricsTotals).mockResolvedValue(
                totals([
                    ['pause', 'succeeded', 40],
                    ['pause', 'filtered', 8],
                ]) as any
            )
            logic = await mountSavedCanvas()
        })

        it('counts the people a step filtered out', () => {
            expect(stepCount(logic.values.stepMetrics, 'pause')).toBe(48)
        })

        it('keeps the canvas counts when the Metrics panel loads another date range', async () => {
            const editorLogic = hogFlowEditorLogic({ id: WORKFLOW_ID })

            await expectLogic(logic, () =>
                editorLogic.actions.loadActionMetricsByIdSuccess({
                    pause: { actionId: 'pause', succeeded: 3, failed: 0, filtered: 0 },
                })
            )

            expect(stepCount(logic.values.stepMetrics, 'pause')).toBe(48)
        })
    })
})
