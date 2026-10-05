import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EXIT_NODE_ID, NEW_WORKFLOW, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowAction, HogFlowEdge } from '../types'
import type { AiDecisionConfig } from './aiDecisionBranches'
import { stepAiDecisionLogic } from './stepAiDecisionLogic'

const DECISION_ID = 'decide'

const delay = (id: string): HogFlowAction => ({
    id,
    name: id,
    description: '',
    type: 'delay',
    config: { delay_duration: '1h' },
})

const decision = (config: Partial<AiDecisionConfig>): HogFlowAction => ({
    id: DECISION_ID,
    name: 'Pick a track',
    description: '',
    type: 'ai_decision',
    config: {
        question: 'Which onboarding track fits this person?',
        answer_type: 'pick_one',
        options: [{ name: 'Self-serve' }, { name: 'Sales' }],
        inputs: {},
        ...config,
    },
})

const branch = (to: string, index: number): HogFlowEdge => ({ from: DECISION_ID, to, type: 'branch', index })
const failed: HogFlowEdge = { from: DECISION_ID, to: EXIT_NODE_ID, type: 'continue' }

describe('stepAiDecisionLogic', () => {
    let logic: ReturnType<typeof stepAiDecisionLogic.build>
    let editorLogic: ReturnType<typeof hogFlowEditorLogic.build>

    const setUpDecision = (config: Partial<AiDecisionConfig>, branchEdges: HogFlowEdge[]): void => {
        const [trigger, exit] = NEW_WORKFLOW.actions
        workflowLogic().actions.setWorkflowInfo({
            actions: [trigger, decision(config), delay('track_a'), delay('track_b'), exit],
            edges: [
                { from: trigger.id, to: DECISION_ID, type: 'continue' },
                ...branchEdges,
                failed,
                { from: 'track_a', to: exit.id, type: 'continue' },
                { from: 'track_b', to: exit.id, type: 'continue' },
            ],
        })
    }

    const decisionBranchEdges = (): Pick<HogFlowEdge, 'to' | 'index'>[] =>
        workflowLogic()
            .values.workflow.edges.filter((edge) => edge.from === DECISION_ID && edge.type === 'branch')
            .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
            .map(({ to, index }) => ({ to, index }))

    const canvasLabels = (): Record<string, string | undefined> =>
        Object.fromEntries(
            editorLogic.values.edges
                .filter((edge) => edge.source === DECISION_ID)
                .map((edge) => [edge.sourceHandle, edge.data?.label])
        )

    beforeEach(() => {
        initKeaTests()
        editorLogic = hogFlowEditorLogic()
        editorLogic.mount()
        logic = stepAiDecisionLogic({ workflowLogicProps: workflowLogic().props, actionId: DECISION_ID })
        logic.mount()
    })

    it('adds a branch edge for a new option ahead of Unsure, labeled with the option name', () => {
        setUpDecision({ unsure_enabled: true }, [branch('track_a', 0), branch('track_b', 1), branch(EXIT_NODE_ID, 2)])

        logic.actions.addOption()
        logic.actions.setOption(2, { name: 'Developer' })

        expect(decisionBranchEdges()).toEqual([
            { to: 'track_a', index: 0 },
            { to: 'track_b', index: 1 },
            { to: EXIT_NODE_ID, index: 2 },
            { to: EXIT_NODE_ID, index: 3 },
        ])
        expect(canvasLabels()).toMatchObject({
            branch_decide_2: 'Developer',
            branch_decide_3: 'Unsure',
            continue_decide: 'If the decision fails',
        })

        logic.actions.setOption(2, { name: 'API first' })

        expect(canvasLabels()).toMatchObject({ branch_decide_2: 'API first' })
    })

    it('removes an option with its edge and keeps later edges on their steps', () => {
        setUpDecision({ options: [{ name: 'Self-serve' }, { name: 'Sales' }, { name: 'Developer' }] }, [
            branch(EXIT_NODE_ID, 0),
            branch('track_a', 1),
            branch('track_b', 2),
        ])

        logic.actions.removeOption(0)

        expect(logic.values.config?.options).toEqual([{ name: 'Sales' }, { name: 'Developer' }])
        expect(decisionBranchEdges()).toEqual([
            { to: 'track_a', index: 0 },
            { to: 'track_b', index: 1 },
        ])
    })

    it('blocks removing an option whose edge is the only way into its step', () => {
        setUpDecision({ options: [{ name: 'Self-serve' }, { name: 'Sales' }, { name: 'Developer' }] }, [
            branch('track_a', 0),
            branch(EXIT_NODE_ID, 1),
            branch('track_b', 2),
        ])

        expect(logic.values.removeOptionDisabledReasons).toEqual([
            'Clean up branching steps first',
            undefined,
            'Clean up branching steps first',
        ])
    })

    it('blocks removing an option when only two are left', () => {
        setUpDecision({}, [branch(EXIT_NODE_ID, 0), branch(EXIT_NODE_ID, 1)])

        expect(logic.values.removeOptionDisabledReasons).toEqual([
            'A question needs at least 2 options',
            'A question needs at least 2 options',
        ])
    })

    it('adds an Unsure edge when Unsure turns on', () => {
        setUpDecision({}, [branch('track_a', 0), branch('track_b', 1)])

        logic.actions.setUnsureEnabled(true)

        expect(decisionBranchEdges()).toEqual([
            { to: 'track_a', index: 0 },
            { to: 'track_b', index: 1 },
            { to: EXIT_NODE_ID, index: 2 },
        ])
        expect(canvasLabels()).toMatchObject({ branch_decide_2: 'Unsure' })
    })

    it.each([
        [10, 20, { yes_threshold: 10, no_threshold: 9 }],
        [1, 20, { yes_threshold: 2, no_threshold: 1 }],
        [50, 20, { yes_threshold: 50, no_threshold: 20 }],
    ])(
        'keeps the No band below a yes threshold of %s when Unsure turns on for Yes or no',
        (yesThreshold, noThreshold, thresholds) => {
            setUpDecision({ answer_type: 'yes_no', yes_threshold: yesThreshold, no_threshold: noThreshold }, [
                branch('track_a', 0),
                branch('track_b', 1),
            ])

            logic.actions.setUnsureEnabled(true)

            expect(logic.values.config).toMatchObject(thresholds)
        }
    )

    it.each([
        ['leads to its own step', 'track_b', 'Clean up branching steps first'],
        ['shares a step with another path', EXIT_NODE_ID, undefined],
    ])('turning Unsure off is guarded when its edge %s', (_, unsureTarget, disabledReason) => {
        setUpDecision({ unsure_enabled: true }, [
            branch('track_a', 0),
            branch(EXIT_NODE_ID, 1),
            branch(unsureTarget, 2),
        ])

        expect(logic.values.unsureOffDisabledReason).toBe(disabledReason)
    })

    it('keeps edges 0 and 1 and adds edge 2 when Yes or no becomes Pick one with three options', () => {
        setUpDecision(
            {
                answer_type: 'yes_no',
                options: [{ name: 'Self-serve' }, { name: 'Sales' }, { name: 'Developer' }],
            },
            [branch('track_a', 0), branch('track_b', 1)]
        )

        logic.actions.setAnswerType('pick_one')

        expect(decisionBranchEdges()).toEqual([
            { to: 'track_a', index: 0 },
            { to: 'track_b', index: 1 },
            { to: EXIT_NODE_ID, index: 2 },
        ])
        expect(canvasLabels()).toMatchObject({
            branch_decide_0: 'Self-serve',
            branch_decide_1: 'Sales',
            branch_decide_2: 'Developer',
        })
    })

    it('starts Pick one with two empty options when Yes or no had none', () => {
        setUpDecision({ answer_type: 'yes_no', options: [] }, [branch('track_a', 0), branch('track_b', 1)])

        logic.actions.setAnswerType('pick_one')

        expect(logic.values.config?.options).toEqual([{ name: '' }, { name: '' }])
        expect(decisionBranchEdges()).toEqual([
            { to: 'track_a', index: 0 },
            { to: 'track_b', index: 1 },
        ])
    })

    it('blocks switching to Yes or no when a dropped answer edge leads to its own step', () => {
        setUpDecision({ options: [{ name: 'Self-serve' }, { name: 'Sales' }, { name: 'Developer' }] }, [
            branch(EXIT_NODE_ID, 0),
            branch('track_a', 1),
            branch('track_b', 2),
        ])

        expect(logic.values.answerTypeDisabledReason).toBe('Clean up branching steps first')
    })

    it('blocks a switch that drops every edge into one step, even when several edges lead there', () => {
        setUpDecision(
            {
                options: [{ name: 'Self-serve' }, { name: 'Sales' }, { name: 'Developer' }, { name: 'Enterprise' }],
            },
            [branch('track_a', 0), branch(EXIT_NODE_ID, 1), branch('track_b', 2), branch('track_b', 3)]
        )

        expect(logic.values.answerTypeDisabledReason).toBe('Clean up branching steps first')
    })

    it('drops the extra answer edges when Pick one becomes Yes or no and keeps the named options', () => {
        setUpDecision({ options: [{ name: 'Self-serve' }, { name: '' }, { name: 'Developer' }] }, [
            branch('track_a', 0),
            branch('track_b', 1),
            branch(EXIT_NODE_ID, 2),
        ])

        logic.actions.setAnswerType('yes_no')

        expect(logic.values.config?.options).toEqual([{ name: 'Self-serve' }, { name: 'Developer' }])
        expect(decisionBranchEdges()).toEqual([
            { to: 'track_a', index: 0 },
            { to: 'track_b', index: 1 },
        ])
        expect(canvasLabels()).toMatchObject({ branch_decide_0: 'Yes', branch_decide_1: 'No' })
    })

    describe('test runs', () => {
        let invocationBodies: Record<string, unknown>[]

        const useTestRunResponse = (response: Record<string, unknown>): void => {
            invocationBodies = []
            useMocks({
                post: {
                    '/api/environments/:team_id/hog_flows/:id/invocations/': async ({ request }) => {
                        invocationBodies.push((await request.json()) as Record<string, unknown>)
                        return [200, response]
                    },
                },
            })
        }

        const threeTracks = {
            options: [{ name: 'Self-serve' }, { name: 'Sales' }, { name: 'Developer' }],
            unsure_enabled: true,
        }
        const trackProbabilities = { 'Self-serve': 0.22, Sales: 0.71, Developer: 0.07 }

        it.each([
            [
                'the chosen answer and its path',
                { status: 'success', execResult: { answer: 'Sales', probabilities: trackProbabilities } },
                {
                    status: 'answered',
                    answers: [
                        { label: 'Self-serve', percent: 22, chosen: false },
                        { label: 'Sales', percent: 71, chosen: true },
                        { label: 'Developer', percent: 7, chosen: false },
                    ],
                    pathLabel: 'Sales',
                },
            ],
            [
                'the Unsure path when no option is chosen',
                { status: 'success', execResult: { answer: 'unsure', probabilities: trackProbabilities } },
                {
                    status: 'answered',
                    answers: [
                        { label: 'Self-serve', percent: 22, chosen: false },
                        { label: 'Sales', percent: 71, chosen: false },
                        { label: 'Developer', percent: 7, chosen: false },
                    ],
                    pathLabel: 'Unsure',
                },
            ],
            [
                'the reason a failed run gives',
                { status: 'error', errors: ['The AI service is busy. Try again in a moment.'] },
                { status: 'failed', message: 'The AI service is busy. Try again in a moment.' },
            ],
        ])('a test with a person runs the real model once and shows %s', async (_, response, outcome) => {
            setUpDecision(threeTracks, [
                branch('track_a', 0),
                branch('track_b', 1),
                branch(EXIT_NODE_ID, 2),
                branch(EXIT_NODE_ID, 3),
            ])
            useTestRunResponse({ nextActionId: null, ...response })

            await expectLogic(logic, () => logic.actions.runPersonTest()).toFinishAllListeners()

            expect(invocationBodies).toEqual([
                expect.objectContaining({ mock_async_functions: false, current_action_id: DECISION_ID }),
            ])
            expect(logic.values.personTestOutcome).toEqual(outcome)
        })

        it('reads yes or no probabilities onto the Yes and No answers', async () => {
            setUpDecision({ answer_type: 'yes_no' }, [branch('track_a', 0), branch('track_b', 1)])
            useTestRunResponse({
                status: 'success',
                execResult: { answer: 'no', probabilities: { yes: 0.3, no: 0.7 } },
            })

            await expectLogic(logic, () => logic.actions.runPersonTest()).toFinishAllListeners()

            expect(logic.values.personTestOutcome).toEqual({
                status: 'answered',
                answers: [
                    { label: 'Yes', percent: 30, chosen: false },
                    { label: 'No', percent: 70, chosen: true },
                ],
                pathLabel: 'No',
            })
        })

        it('measures what is sent from a mocked run that spends nothing', async () => {
            setUpDecision({}, [branch('track_a', 0), branch('track_b', 1)])
            useTestRunResponse({
                status: 'success',
                execResult: {
                    answer: 'Self-serve',
                    probabilities: { 'Self-serve': 1, Sales: 0 },
                    context: { message: 'We need SSO' },
                    context_bytes: 25,
                },
            })

            await expectLogic(logic, () => logic.actions.loadContextPreview()).toFinishAllListeners()

            expect(invocationBodies).toEqual([
                expect.objectContaining({ mock_async_functions: true, current_action_id: DECISION_ID }),
            ])
            expect(logic.values.contextPreview).toEqual({
                status: 'rendered',
                context: { message: 'We need SSO' },
                bytes: 25,
            })
        })
    })
})
