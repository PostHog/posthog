import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction, HogFlowActionNode } from '../types'
import { hogFlowOutputMappingLogic, normalizeOutputVariable } from './hogFlowOutputMappingLogic'

const makeActionNode = (id: string, outputVariable?: HogFlowAction['output_variable']): HogFlowActionNode => ({
    id,
    type: 'hogFlowAction',
    position: { x: 0, y: 0 },
    data: {
        id,
        type: 'function',
        name: 'Test action',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: {} as any,
        ...(outputVariable !== undefined ? { output_variable: outputVariable } : {}),
    } as HogFlowAction,
})

describe('hogFlowOutputMappingLogic', () => {
    describe('normalizeOutputVariable', () => {
        it.each([
            { description: 'null', raw: null, expected: [] },
            { description: 'undefined', raw: undefined, expected: [] },
            {
                description: 'single object with key',
                raw: { key: 'myVar', result_path: 'body.id' },
                expected: [{ key: 'myVar', result_path: 'body.id', spread: undefined }],
            },
            {
                description: 'single object with key and spread',
                raw: { key: 'myVar', result_path: null, spread: true },
                expected: [{ key: 'myVar', result_path: '', spread: true }],
            },
            {
                description: 'single object without key is treated as empty',
                raw: { key: '', result_path: 'body.id' },
                expected: [],
            },
            {
                description: 'array of mappings',
                raw: [
                    { key: 'a', result_path: 'body.a' },
                    { key: 'b', result_path: null },
                ],
                expected: [
                    { key: 'a', result_path: 'body.a', spread: undefined },
                    { key: 'b', result_path: '', spread: undefined },
                ],
            },
            {
                description: 'array with spread flags',
                raw: [
                    { key: 'x', result_path: null, spread: true },
                    { key: 'y', result_path: 'foo', spread: false },
                ],
                expected: [
                    { key: 'x', result_path: '', spread: true },
                    { key: 'y', result_path: 'foo', spread: false },
                ],
            },
        ])('returns $expected given $description', ({ raw, expected }) => {
            expect(normalizeOutputVariable(raw as HogFlowAction['output_variable'])).toEqual(expected)
        })
    })

    describe('logic', () => {
        let logic: ReturnType<typeof hogFlowOutputMappingLogic.build>
        let editorLogic: ReturnType<typeof hogFlowEditorLogic.build>
        let wfLogic: ReturnType<typeof workflowLogic.build>
        const WORKFLOW_ID = 'test-workflow'

        beforeEach(() => {
            initKeaTests()

            wfLogic = workflowLogic({ id: WORKFLOW_ID })
            wfLogic.mount()

            editorLogic = hogFlowEditorLogic({ id: WORKFLOW_ID })
            editorLogic.mount()

            logic = hogFlowOutputMappingLogic({ id: WORKFLOW_ID })
            logic.mount()
        })

        describe('initial state', () => {
            it('starts with empty mappings and null pendingPath', () => {
                expect(logic.values.mappings).toEqual([])
                expect(logic.values.pendingPath).toBeNull()
                expect(logic.values.testError).toBeNull()
                expect(logic.values.testResultData).toBeNull()
            })
        })

        describe('setSelectedActionId resets', () => {
            it('clears mappings, pendingPath, testError and testResultData', async () => {
                logic.actions.setMappings([{ key: 'foo', result_path: 'bar' }])
                logic.actions.setTestError('some error')
                logic.actions.setTestResultData({ some: 'data' })

                // Set pendingPath by using 2+ mappings then selectPath
                logic.actions.initMappings([
                    { key: 'a', result_path: 'x' },
                    { key: 'b', result_path: 'y' },
                ])
                logic.actions.selectPath('event.properties.foo')
                expect(logic.values.pendingPath).toBe('event.properties.foo')

                await expectLogic(logic, () => {
                    logic.actions.setSelectedActionId('new-action-id')
                }).toMatchValues({
                    mappings: [],
                    pendingPath: null,
                    testError: null,
                    testResultData: null,
                })
            })

            it('initializes mappings from selectedNode when action has a single mapping', async () => {
                const node = makeActionNode('action-1', { key: 'myVar', result_path: 'body.id' })

                // Populate the editor's node list synchronously, then select the node
                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId('action-1')
                }).toMatchValues({
                    selectedNode: node,
                })

                await expectLogic(logic, () => {
                    logic.actions.setSelectedActionId('action-1')
                })
                    .toDispatchActions(['initMappings'])
                    .toMatchValues({
                        mappings: [{ key: 'myVar', result_path: 'body.id', spread: undefined }],
                    })
            })

            it('initializes empty mappings when selected action has no output_variable', async () => {
                const node = makeActionNode('action-2', null)

                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId('action-2')
                }).toMatchValues({
                    selectedNode: node,
                })

                await expectLogic(logic, () => {
                    logic.actions.setSelectedActionId('action-2')
                })
                    .toDispatchActions(['initMappings'])
                    .toMatchValues({
                        mappings: [],
                    })
            })
        })

        describe('initMappings vs setMappings', () => {
            it('initMappings does NOT trigger persistence', async () => {
                await expectLogic(logic, () => {
                    logic.actions.initMappings([{ key: 'existing', result_path: 'body' }])
                })
                    .toDispatchActions(['initMappings'])
                    .toNotHaveDispatchedActions([
                        (action: any) => action.type === wfLogic.actionCreators.setWorkflowAction('', {} as any).type,
                    ])
                    .toMatchValues({
                        mappings: [{ key: 'existing', result_path: 'body' }],
                    })
            })

            it('setMappings triggers persistence via setWorkflowAction when a node is selected', async () => {
                const node = makeActionNode('action-persist')
                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId('action-persist')
                }).toMatchValues({ selectedNode: node })

                await expectLogic(logic, () => {
                    logic.actions.setMappings([{ key: 'foo', result_path: 'bar' }])
                }).toDispatchActions([
                    (action: any) => action.type === wfLogic.actionCreators.setWorkflowAction('', {} as any).type,
                ])
            })
        })

        describe('persistMappings format (output_variable in workflow)', () => {
            const ACTION_ID = 'persist-format-action'

            // persistMappings calls setWorkflowAction; we capture the output_variable from the
            // dispatched action payload rather than reading from workflowLogic state, because
            // setWorkflowAction only updates actions that already exist in the workflow actions list.
            it.each([
                {
                    description: '0 mappings with keys → output_variable: null',
                    mappings: [{ key: '', result_path: 'body' }],
                    expected: null,
                },
                {
                    description: '1 mapping with key → single object (not array)',
                    mappings: [{ key: 'myVar', result_path: 'body.id' }],
                    expected: { key: 'myVar', result_path: 'body.id' },
                },
                {
                    description: '2 mappings with keys → array',
                    mappings: [
                        { key: 'varA', result_path: 'body.a' },
                        { key: 'varB', result_path: 'body.b' },
                    ],
                    expected: [
                        { key: 'varA', result_path: 'body.a' },
                        { key: 'varB', result_path: 'body.b' },
                    ],
                },
                {
                    description: 'empty keys filtered out: 1 valid key → single object',
                    mappings: [
                        { key: '', result_path: 'body.a' },
                        { key: 'varB', result_path: 'body.b' },
                    ],
                    expected: { key: 'varB', result_path: 'body.b' },
                },
                {
                    description: 'empty result_path persisted as null',
                    mappings: [{ key: 'myVar', result_path: '' }],
                    expected: { key: 'myVar', result_path: null },
                },
                {
                    description: 'spread: true is included',
                    mappings: [{ key: 'myVar', result_path: '', spread: true }],
                    expected: { key: 'myVar', result_path: null, spread: true },
                },
            ])('$description', async ({ mappings, expected }) => {
                const node = makeActionNode(ACTION_ID)
                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId(ACTION_ID)
                }).toMatchValues({ selectedNode: node })

                let capturedOutputVariable: unknown = 'NOT_CAPTURED'
                await expectLogic(logic, () => {
                    logic.actions.setMappings(mappings)
                })
                    .toDispatchActions([
                        (action: any) => {
                            if (action.type === wfLogic.actionCreators.setWorkflowAction('', {} as any).type) {
                                capturedOutputVariable = action.payload.action?.output_variable ?? null
                            }
                            return action.type === wfLogic.actionCreators.setWorkflowAction('', {} as any).type
                        },
                    ])
                    .toFinishAllListeners()

                expect(capturedOutputVariable).toEqual(expected)
            })

            it('does not include spread field when spread is falsy', async () => {
                const node = makeActionNode(ACTION_ID)
                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId(ACTION_ID)
                }).toMatchValues({ selectedNode: node })

                let capturedOutputVariable: any = 'NOT_CAPTURED'
                await expectLogic(logic, () => {
                    logic.actions.setMappings([{ key: 'myVar', result_path: 'x', spread: false }])
                })
                    .toDispatchActions([
                        (action: any) => {
                            if (action.type === wfLogic.actionCreators.setWorkflowAction('', {} as any).type) {
                                capturedOutputVariable = action.payload.action?.output_variable ?? null
                            }
                            return action.type === wfLogic.actionCreators.setWorkflowAction('', {} as any).type
                        },
                    ])
                    .toFinishAllListeners()

                expect(capturedOutputVariable?.spread).toBeUndefined()
            })
        })

        describe('selectPath behavior', () => {
            const ACTION_ID = 'select-path-action'

            beforeEach(async () => {
                const node = makeActionNode(ACTION_ID)
                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId(ACTION_ID)
                }).toMatchValues({ selectedNode: node })
            })

            it('creates a new mapping with the path when there are 0 existing mappings', async () => {
                expect(logic.values.mappings).toHaveLength(0)

                await expectLogic(logic, () => {
                    logic.actions.selectPath('event.properties.email')
                })
                    .toDispatchActions(['setMappings'])
                    .toMatchValues({
                        mappings: [{ key: '', result_path: 'event.properties.email' }],
                    })
            })

            it('sets pendingPath without calling setMappings when there are 2 or more mappings', async () => {
                logic.actions.initMappings([
                    { key: 'a', result_path: 'x' },
                    { key: 'b', result_path: 'y' },
                ])

                await expectLogic(logic, () => {
                    logic.actions.selectPath('event.properties.new')
                })
                    .toNotHaveDispatchedActions(['setMappings'])
                    .toMatchValues({
                        pendingPath: 'event.properties.new',
                        mappings: [
                            { key: 'a', result_path: 'x' },
                            { key: 'b', result_path: 'y' },
                        ],
                    })
            })

            it('updates the first mapping result_path when there is exactly 1 existing mapping', async () => {
                logic.actions.initMappings([{ key: 'myVar', result_path: '' }])

                await expectLogic(logic, () => {
                    logic.actions.selectPath('event.properties.email')
                })
                    .toDispatchActions(['setMappings'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        mappings: [{ key: 'myVar', result_path: 'event.properties.email' }],
                    })
            })
        })

        describe('assignPendingPathToMapping', () => {
            const ACTION_ID = 'assign-path-action'

            beforeEach(async () => {
                const node = makeActionNode(ACTION_ID)
                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId(ACTION_ID)
                }).toMatchValues({ selectedNode: node })
            })

            it('assigns path to the specified mapping index and clears pendingPath', async () => {
                logic.actions.initMappings([
                    { key: 'a', result_path: 'old.path' },
                    { key: 'b', result_path: 'other.path' },
                ])
                // Trigger pendingPath via selectPath (2 mappings - won't call setMappings)
                logic.actions.selectPath('event.properties.new')
                expect(logic.values.pendingPath).toBe('event.properties.new')

                await expectLogic(logic, () => {
                    logic.actions.assignPendingPathToMapping(1, 'event.properties.new')
                })
                    .toDispatchActions(['setMappings'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        pendingPath: null,
                        mappings: [
                            { key: 'a', result_path: 'old.path' },
                            { key: 'b', result_path: 'event.properties.new' },
                        ],
                    })
            })

            it('assigns path to index 0 when first mapping is targeted', async () => {
                logic.actions.initMappings([
                    { key: 'first', result_path: '' },
                    { key: 'second', result_path: '' },
                ])

                await expectLogic(logic, () => {
                    logic.actions.assignPendingPathToMapping(0, 'event.uuid')
                })
                    .toDispatchActions(['setMappings'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        mappings: [
                            { key: 'first', result_path: 'event.uuid' },
                            { key: 'second', result_path: '' },
                        ],
                        pendingPath: null,
                    })
            })
        })

        describe('cancelPendingPath', () => {
            it('clears pendingPath without modifying mappings', async () => {
                logic.actions.initMappings([
                    { key: 'a', result_path: 'x' },
                    { key: 'b', result_path: 'y' },
                ])
                logic.actions.selectPath('event.something')
                expect(logic.values.pendingPath).toBe('event.something')

                await expectLogic(logic, () => {
                    logic.actions.cancelPendingPath()
                }).toMatchValues({
                    pendingPath: null,
                    mappings: [
                        { key: 'a', result_path: 'x' },
                        { key: 'b', result_path: 'y' },
                    ],
                })
            })
        })

        describe('updateMappingResultPath', () => {
            const ACTION_ID = 'update-result-path-action'

            beforeEach(async () => {
                const node = makeActionNode(ACTION_ID)
                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId(ACTION_ID)
                }).toMatchValues({ selectedNode: node })
            })

            it.each([
                {
                    description: 'first mapping (index 0)',
                    index: 0,
                    initial: [
                        { key: 'a', result_path: 'old' },
                        { key: 'b', result_path: 'keep' },
                    ],
                    expected: [
                        { key: 'a', result_path: 'new.path' },
                        { key: 'b', result_path: 'keep' },
                    ],
                },
                {
                    description: 'middle mapping (index 1)',
                    index: 1,
                    initial: [
                        { key: 'a', result_path: 'first' },
                        { key: 'b', result_path: 'second' },
                        { key: 'c', result_path: 'third' },
                    ],
                    expected: [
                        { key: 'a', result_path: 'first' },
                        { key: 'b', result_path: 'new.path' },
                        { key: 'c', result_path: 'third' },
                    ],
                },
            ])('updates $description leaving others unchanged', async ({ index, initial, expected }) => {
                logic.actions.initMappings(initial)

                await expectLogic(logic, () => {
                    logic.actions.updateMappingResultPath(index, 'new.path')
                }).toMatchValues({
                    mappings: expected,
                })
            })
        })

        describe('addMapping and removeMapping', () => {
            it('addMapping appends an empty mapping to the existing list', async () => {
                logic.actions.initMappings([{ key: 'existing', result_path: 'x' }])

                await expectLogic(logic, () => {
                    logic.actions.addMapping()
                }).toMatchValues({
                    mappings: [
                        { key: 'existing', result_path: 'x' },
                        { key: '', result_path: '' },
                    ],
                })
            })

            it('removeMapping removes the mapping at the specified index', async () => {
                logic.actions.initMappings([
                    { key: 'a', result_path: 'x' },
                    { key: 'b', result_path: 'y' },
                    { key: 'c', result_path: 'z' },
                ])

                await expectLogic(logic, () => {
                    logic.actions.removeMapping(1)
                }).toMatchValues({
                    mappings: [
                        { key: 'a', result_path: 'x' },
                        { key: 'c', result_path: 'z' },
                    ],
                })
            })
        })

        describe('testError and testResultData', () => {
            it.each([
                { description: 'string error message', error: 'something went wrong' },
                { description: 'null to clear error', error: null },
            ])('setTestError stores $description', async ({ error }) => {
                await expectLogic(logic, () => {
                    logic.actions.setTestError(error)
                }).toMatchValues({
                    testError: error,
                })
            })

            it('setTestResultData updates testResultData', async () => {
                const data = { key: 'value', nested: { count: 42 } }

                await expectLogic(logic, () => {
                    logic.actions.setTestResultData(data)
                }).toMatchValues({
                    testResultData: data,
                })
            })
        })

        describe('selectedAction selector', () => {
            it('returns null when no node is selected', () => {
                expect(logic.values.selectedAction).toBeNull()
            })

            it('returns the data of the currently selected node', async () => {
                const node = makeActionNode('sel-action', { key: 'myVar', result_path: 'body' })

                await expectLogic(editorLogic, () => {
                    editorLogic.actions.setNodesRaw([node])
                    editorLogic.actions.setSelectedNodeId('sel-action')
                }).toMatchValues({ selectedNode: node })

                await expectLogic(logic).toMatchValues({
                    selectedAction: node.data,
                })
            })
        })
    })
})
