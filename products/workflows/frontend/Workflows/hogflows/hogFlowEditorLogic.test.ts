import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID, workflowLogic } from '../workflowLogic'
import { computeInsertEdges, computeMoveEdges, hogFlowEditorLogic } from './hogFlowEditorLogic'
import { HogFlow, HogFlowAction, HogFlowActionEdge, HogFlowActionNode } from './types'

type Edge = HogFlow['edges'][0]
const edge = (from: string, to: string, type: 'continue' | 'branch', index?: number): Edge => ({
    from,
    to,
    type,
    index,
})

describe('computeMoveEdges', () => {
    it.each([
        {
            name: 'move node forward in linear chain',
            edges: [edge('trigger', 'A', 'continue'), edge('A', 'B', 'continue'), edge('B', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('B', 'exit', 'continue'),
            isBranchJoin: false,
            expected: [edge('trigger', 'B', 'continue'), edge('B', 'A', 'continue'), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node backward in linear chain',
            edges: [edge('trigger', 'A', 'continue'), edge('A', 'B', 'continue'), edge('B', 'exit', 'continue')],
            movingNodeId: 'B',
            targetEdge: edge('trigger', 'A', 'continue'),
            isBranchJoin: false,
            expected: [edge('A', 'exit', 'continue'), edge('trigger', 'B', 'continue'), edge('B', 'A', 'continue')],
        },
        {
            name: 'move node from continue branch to branch edge of conditional',
            edges: [edge('cond', 'exit', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'exit', 'branch', 0),
            isBranchJoin: false,
            expected: [edge('cond', 'exit', 'continue'), edge('cond', 'A', 'branch', 0), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node from branch edge to continue branch of conditional',
            edges: [edge('cond', 'A', 'branch', 0), edge('cond', 'exit', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'exit', 'continue'),
            isBranchJoin: false,
            expected: [edge('cond', 'exit', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node onto edge it is already the target of (no-op position)',
            edges: [edge('cond', 'A', 'branch', 0), edge('cond', 'exit', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'A', 'branch', 0),
            isBranchJoin: false,
            expected: [edge('cond', 'exit', 'continue'), edge('cond', 'A', 'branch', 0), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node to branch join dropzone inserts on all branches',
            edges: [edge('cond', 'exit', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'exit', 'branch', 0),
            isBranchJoin: true,
            expected: [edge('cond', 'A', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node when both conditional edges point to it (branch join, move to branch)',
            edges: [edge('cond', 'A', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'A', 'branch', 0),
            isBranchJoin: false,
            expected: [edge('cond', 'exit', 'continue'), edge('cond', 'A', 'branch', 0), edge('A', 'exit', 'continue')],
        },
    ])('$name', ({ edges, movingNodeId, targetEdge, isBranchJoin, expected }) => {
        const result = computeMoveEdges(edges, movingNodeId, targetEdge, isBranchJoin)
        expect(result).toEqual(expected)
    })

    it('inserts a step after only the nested split paths', () => {
        const edges = [
            edge('trigger', 'outer', 'continue'),
            edge('outer', 'paid', 'branch', 0),
            edge('outer', 'onboarding', 'branch', 1),
            edge('outer', 'at-risk', 'continue'),
            edge('paid', 'shared', 'continue'),
            edge('at-risk', 'shared', 'continue'),
            edge('onboarding', 'guided', 'branch', 0),
            edge('onboarding', 'self-serve', 'branch', 1),
            edge('onboarding', 'shared', 'continue'),
            edge('guided', 'shared', 'continue'),
            edge('self-serve', 'shared', 'continue'),
            edge('shared', 'exit', 'continue'),
        ]

        expect(
            computeInsertEdges(edges, 'after-onboarding', 0, [
                edge('guided', 'shared', 'continue'),
                edge('self-serve', 'shared', 'continue'),
                edge('onboarding', 'shared', 'continue'),
            ])
        ).toEqual([
            edge('trigger', 'outer', 'continue'),
            edge('outer', 'paid', 'branch', 0),
            edge('outer', 'onboarding', 'branch', 1),
            edge('outer', 'at-risk', 'continue'),
            edge('paid', 'shared', 'continue'),
            edge('at-risk', 'shared', 'continue'),
            edge('onboarding', 'guided', 'branch', 0),
            edge('onboarding', 'self-serve', 'branch', 1),
            edge('shared', 'exit', 'continue'),
            edge('onboarding', 'after-onboarding', 'continue'),
            edge('guided', 'after-onboarding', 'continue'),
            edge('self-serve', 'after-onboarding', 'continue'),
            edge('after-onboarding', 'shared', 'continue'),
        ])
    })

    it('moves a step after only the nested split paths', () => {
        const edges = [
            edge('trigger', 'move', 'continue'),
            edge('move', 'outer', 'continue'),
            edge('outer', 'paid', 'branch', 0),
            edge('outer', 'onboarding', 'branch', 1),
            edge('outer', 'at-risk', 'continue'),
            edge('paid', 'shared', 'continue'),
            edge('at-risk', 'shared', 'continue'),
            edge('onboarding', 'guided', 'branch', 0),
            edge('onboarding', 'self-serve', 'branch', 1),
            edge('onboarding', 'shared', 'continue'),
            edge('guided', 'shared', 'continue'),
            edge('self-serve', 'shared', 'continue'),
            edge('shared', 'exit', 'continue'),
        ]
        const joinEdges = [
            edge('guided', 'shared', 'continue'),
            edge('self-serve', 'shared', 'continue'),
            edge('onboarding', 'shared', 'continue'),
        ]

        expect(computeMoveEdges(edges, 'move', joinEdges[0], true, joinEdges)).toEqual([
            edge('trigger', 'outer', 'continue'),
            edge('outer', 'paid', 'branch', 0),
            edge('outer', 'onboarding', 'branch', 1),
            edge('outer', 'at-risk', 'continue'),
            edge('paid', 'shared', 'continue'),
            edge('at-risk', 'shared', 'continue'),
            edge('onboarding', 'guided', 'branch', 0),
            edge('onboarding', 'self-serve', 'branch', 1),
            edge('shared', 'exit', 'continue'),
            edge('onboarding', 'move', 'continue'),
            edge('guided', 'move', 'continue'),
            edge('self-serve', 'move', 'continue'),
            edge('move', 'shared', 'continue'),
        ])
    })

    it('returns null when moving node has no outgoing edge', () => {
        const edges = [edge('trigger', 'A', 'continue')]
        expect(computeMoveEdges(edges, 'A', edge('trigger', 'A', 'continue'), false)).toBeNull()
    })

    it('returns null when target edge cannot be found after bypass', () => {
        const edges = [edge('trigger', 'A', 'continue'), edge('A', 'exit', 'continue')]
        const nonexistent = edge('X', 'Y', 'continue')
        expect(computeMoveEdges(edges, 'A', nonexistent, false)).toBeNull()
    })
})

describe('hogFlowEditorLogic', () => {
    let logic: ReturnType<typeof hogFlowEditorLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = hogFlowEditorLogic()
        logic.mount()
    })

    it('resolves the selected action while React Flow nodes are still laying out', () => {
        const action = logic.values.workflow.actions[0]
        logic.actions.setNodesRaw([])
        logic.actions.setSelectedNodeId(action.id)

        expect(logic.values.selectedNode).toMatchObject({ id: action.id, data: action })
    })

    it('keeps edits made while "Save as team default" was saving', () => {
        const email = {
            id: 'email',
            name: 'Send email',
            description: '',
            type: 'function_email',
            created_at: 0,
            updated_at: 0,
            config: {
                template_id: 'template-email',
                inputs: {},
                utm_tags_enabled: true,
                utm_params: { utm_source: 'partner', utm_campaign: 'spring' },
                utm_params_from_default: [],
            },
        } as HogFlowAction
        workflowLogic().actions.setWorkflowInfo({
            actions: [NEW_WORKFLOW.actions[0], email, NEW_WORKFLOW.actions[1]],
            edges: [edge(TRIGGER_NODE_ID, email.id, 'continue'), edge(email.id, EXIT_NODE_ID, 'continue')],
        })
        const saved = { utm_source: 'partner', utm_campaign: 'spring' }
        logic.actions.setWorkflowAction(email.id, {
            ...email,
            name: 'Renamed while saving',
            config: { ...email.config, utm_params: { utm_source: 'partner', utm_campaign: 'summer' } },
        } as HogFlowAction)

        logic.actions.markUtmSavedAsTeamDefault(email.id, saved)

        const latest = logic.values.workflow.actions.find((action) => action.id === email.id)
        expect(latest).toMatchObject({
            name: 'Renamed while saving',
            config: {
                utm_params: { utm_source: 'partner', utm_campaign: 'summer' },
                utm_params_from_default: ['utm_source', 'utm_medium', 'utm_content'],
            },
        })
    })

    it.each([
        {
            case: 'a delay',
            step: {
                id: 'step',
                name: 'Delay',
                description: '',
                type: 'delay',
                created_at: 0,
                updated_at: 0,
                config: { delay_duration: '1d' },
            } as HogFlowAction,
        },
        {
            case: 'an email with its own UTM settings',
            step: {
                id: 'step',
                name: 'Send email',
                description: '',
                type: 'function_email',
                created_at: 0,
                updated_at: 0,
                config: {
                    template_id: 'template-email',
                    inputs: {},
                    utm_tags_enabled: false,
                    utm_params: { utm_source: 'partner' },
                    utm_params_from_default: ['utm_medium'],
                },
            } as HogFlowAction,
        },
    ])('copies $case onto the edge below it', ({ step }) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                capture_workflows_engagement_events: false,
                email_utm_tags_enabled: true,
                email_utm_params: { utm_source: 'newsletter' },
            },
        })
        workflowLogic().actions.setWorkflowInfo({
            actions: [NEW_WORKFLOW.actions[0], step, NEW_WORKFLOW.actions[1]],
            edges: [edge(TRIGGER_NODE_ID, step.id, 'continue'), edge(step.id, EXIT_NODE_ID, 'continue')],
        })

        logic.actions.startCopyingNode({
            id: step.id,
            type: step.type,
            data: step,
            position: { x: 0, y: 0 },
        } as HogFlowActionNode)
        logic.actions.onDrop(undefined, edge(step.id, EXIT_NODE_ID, 'continue'))

        const duplicatedAction = logic.values.workflow.actions.find(
            (action) => action.id !== step.id && action.type === step.type
        )
        expect(duplicatedAction).toMatchObject({ name: step.name, config: step.config })
        expect(logic.values.workflow.edges).toEqual([
            edge(TRIGGER_NODE_ID, step.id, 'continue'),
            edge(step.id, duplicatedAction!.id, 'continue'),
            edge(duplicatedAction!.id, EXIT_NODE_ID, 'continue'),
        ])
    })

    describe('graph identity across rebuilds', () => {
        // Auto-save round-trips rebuild the graph from the workflow; without id-based
        // reconciliation every node and edge object is recreated each time and every ReactFlow
        // subtree re-renders, the detached-DOM churn this exists to prevent. Fixed timestamps so
        // two calls produce deep-equal flows.
        const makeFlow = (branchName: string = 'Branch'): HogFlow => ({
            id: 'test-flow',
            team_id: 1,
            version: 1,
            name: 'Test Flow',
            status: 'draft',
            exit_condition: 'exit_only_at_end',
            actions: [
                {
                    id: 'trigger',
                    name: 'Trigger',
                    description: '',
                    type: 'trigger',
                    created_at: 1,
                    updated_at: 1,
                    config: { type: 'event', filters: {} },
                },
                {
                    id: 'branch',
                    name: branchName,
                    description: '',
                    type: 'conditional_branch',
                    created_at: 1,
                    updated_at: 1,
                    config: { conditions: [{ filters: {} }] },
                },
                {
                    id: 'exit',
                    name: 'Exit',
                    description: '',
                    type: 'exit',
                    created_at: 1,
                    updated_at: 1,
                    config: { reason: '' },
                },
            ],
            edges: [
                { from: 'trigger', to: 'branch', type: 'continue' },
                { from: 'branch', to: 'exit', type: 'branch', index: 0 },
                { from: 'branch', to: 'exit', type: 'continue' },
            ],
            updated_at: '2026-01-01T00:00:00Z',
            created_at: '2026-01-01T00:00:00Z',
        })

        // Each rebuild finishes by dispatching setNodesRaw from the async layout listener, and
        // kea-test-utils consumes matched actions in order, so awaiting one setNodesRaw per
        // rebuild is the deterministic "layout finished" signal.
        const applyFlow = async (flow: HogFlow): Promise<void> => {
            await expectLogic(logic, () => logic.actions.resetFlowFromHogFlow(flow)).toDispatchActions(['setNodesRaw'])
        }

        beforeEach(async () => {
            // Let the mount-time subscription rebuild (from workflowLogic's template flow) land
            // first so it can't clobber the flows the tests apply.
            await expectLogic(logic).toDispatchActions(['setNodesRaw'])
        })

        it('keeps node and edge references stable across a deep-equal rebuild', async () => {
            await applyFlow(makeFlow())
            const initialNodes = logic.values.nodes
            const initialEdges = logic.values.edges
            expect(initialNodes.length).toBeGreaterThan(0)

            // Freshly constructed but deep-equal, as an auto-save round-trip would deliver.
            await applyFlow(makeFlow())

            // Array identity, not just item identity: ReactFlow diffs its nodes/edges props by
            // reference, so a fresh array wrapper per rebuild re-syncs its store every render.
            expect(logic.values.nodes).toBe(initialNodes)
            expect(logic.values.edges).toBe(initialEdges)
        })

        it('replaces only the changed node reference when one action changes', async () => {
            await applyFlow(makeFlow())
            const initialNodes = logic.values.nodes

            await applyFlow(makeFlow('Renamed branch'))

            const byId = (id: string): HogFlowActionNode | undefined =>
                logic.values.nodes.find((node) => node.id === id)
            expect(byId('trigger')).toBe(initialNodes.find((node) => node.id === 'trigger'))
            expect(byId('exit')).toBe(initialNodes.find((node) => node.id === 'exit'))
            expect(byId('branch')).not.toBe(initialNodes.find((node) => node.id === 'branch'))
            expect(byId('branch')?.data.name).toBe('Renamed branch')
        })
    })

    describe('showDropzones branch-join placement', () => {
        const makeNode = (id: string): HogFlowActionNode =>
            ({
                id,
                type: 'action',
                data: { id, type: 'exit', name: id, description: '', config: {} } as unknown as HogFlowAction,
                position: { x: 0, y: 0 },
            }) as HogFlowActionNode

        const makeEdge = (
            from: string,
            to: string,
            type: 'continue' | 'branch',
            index?: number
        ): HogFlowActionEdge => ({
            id: `${from}->${to} ${type} ${index ?? ''}`.trim(),
            source: from,
            target: to,
            data: { edge: { from, to, type, index } },
        })

        const branchJoinDropzones = (): { id: string; targetId: string }[] =>
            logic.values.dropzoneNodes
                .filter((n) => n.data.isBranchJoinDropzone)
                .map((n) => ({ id: n.id, targetId: n.data.edge.target as string }))

        it.each([
            {
                name: 'branches are empty (regression)',
                nodes: ['trigger', 'cond', 'exit'],
                edges: [
                    makeEdge('trigger', 'cond', 'continue'),
                    makeEdge('cond', 'exit', 'branch', 0),
                    makeEdge('cond', 'exit', 'branch', 1),
                    makeEdge('cond', 'exit', 'continue'),
                ],
                expected: [{ id: 'dropzone_target_exit_branch_join', targetId: 'exit' }],
            },
            {
                name: 'branches are populated',
                nodes: ['trigger', 'cond', 'email1', 'email2', 'exit'],
                edges: [
                    makeEdge('trigger', 'cond', 'continue'),
                    makeEdge('cond', 'email1', 'branch', 0),
                    makeEdge('cond', 'email2', 'branch', 1),
                    makeEdge('cond', 'exit', 'continue'),
                    makeEdge('email1', 'exit', 'continue'),
                    makeEdge('email2', 'exit', 'continue'),
                ],
                expected: [{ id: 'dropzone_target_exit_branch_join', targetId: 'exit' }],
            },
            {
                name: 'purely linear chain - no dropzone',
                nodes: ['trigger', 'a', 'exit'],
                edges: [makeEdge('trigger', 'a', 'continue'), makeEdge('a', 'exit', 'continue')],
                expected: [],
            },
        ])('shows correct branch-join dropzones when $name', ({ nodes, edges, expected }) => {
            logic.actions.setNodesRaw(nodes.map(makeNode))
            logic.actions.setEdges(edges)
            logic.actions.showDropzones()
            expect(branchJoinDropzones()).toEqual(expected)
        })
    })
})
