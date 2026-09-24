import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import { tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'

import { captureCommandFeedback } from '../utils/feedbackEvents'
import { runInteractionLogic, type RunInteractionLogicProps } from './runInteractionLogic'
import { runSlashCommandsLogic } from './runSlashCommandsLogic'
import { runStreamLogic } from './runStreamLogic'

jest.mock('./runStreamLogic', () => {
    const { kea, actions, key, path, props, reducers } = jest.requireActual('kea')
    return {
        runStreamLogic: kea([
            path(['test', 'runStreamLogicStub']),
            props({}),
            key((p: { streamKey: string }) => p.streamKey),
            actions({ setStubCommands: (commands: unknown[]) => ({ commands }) }),
            reducers({
                availableCommands: [[], { setStubCommands: (_: unknown, { commands }: any) => commands }],
                bootstrappedRunId: ['run-1', {}],
                bootstrappedTaskId: ['task-1', {}],
                contextUsage: [null, {}],
                traceId: ['trace-1', {}],
            }),
        ]),
    }
})

jest.mock('./runInteractionLogic', () => {
    const { kea, actions, key, path, props, reducers } = jest.requireActual('kea')
    return {
        runInteractionLogic: kea([
            path(['test', 'runInteractionLogicStub']),
            props({}),
            key((p: { runId: string }) => p.runId),
            actions({
                setDraft: (draft: string) => ({ draft }),
                setStubTerminal: (terminal: boolean) => ({ terminal }),
                submitComposerForm: true,
                resetComposerForm: true,
            }),
            reducers({
                composerForm: [
                    { draft: '' },
                    {
                        setDraft: (_: unknown, { draft }: { draft: string }) => ({ draft }),
                        resetComposerForm: () => ({ draft: '' }),
                    },
                ],
                isTerminal: [false, { setStubTerminal: (_: boolean, { terminal }: any) => terminal }],
            }),
        ]),
    }
})

jest.mock('scenes/projectLogic', () => {
    const { kea, path, reducers } = jest.requireActual('kea')
    return { projectLogic: kea([path(['test', 'projectLogicStub']), reducers({ currentProjectId: [997, {}] })]) }
})

jest.mock('lib/components/Support/supportLogic', () => {
    const { kea, actions, path } = jest.requireActual('kea')
    return {
        supportLogic: kea([
            path(['test', 'supportLogicStub']),
            actions({ openSupportForm: (values: unknown) => values }),
        ]),
    }
})

jest.mock('products/tasks/frontend/generated/api', () => ({ tasksRunsCommandCreate: jest.fn() }))
jest.mock('../utils/feedbackEvents', () => ({ captureCommandFeedback: jest.fn() }))
jest.mock('lib/lemon-ui/LemonToast', () => ({ lemonToast: { error: jest.fn(), success: jest.fn() } }))

describe('runSlashCommandsLogic', () => {
    const logicProps: RunInteractionLogicProps = { taskId: 'task-1', runId: 'run-1', currentRuntimeAdapter: 'claude' }
    let logic: ReturnType<typeof runSlashCommandsLogic.build>
    let interaction: ReturnType<typeof runInteractionLogic.build>

    const setDraft = (draft: string): void => (interaction.actions as any).setDraft(draft)

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        interaction = runInteractionLogic(logicProps)
        interaction.mount()
        ;(runStreamLogic({ streamKey: 'run-1' }).actions as any).setStubCommands([
            { name: 'compact', description: 'Compact the conversation' },
            { name: 'init', description: 'Initialize a CLAUDE.md file' },
        ])
        logic = runSlashCommandsLogic(logicProps)
        logic.mount()
    })

    it.each([
        ['an agent command', '/compact'],
        ['a hidden harness built-in', '/init'],
        ['plain text', 'what changed?'],
    ])('sends %s to the agent', async (_label, draft) => {
        setDraft(draft)

        await expectLogic(logic, () => logic.actions.submitComposer()).toFinishAllListeners()

        await expectLogic(interaction).toDispatchActions(['submitComposerForm'])
        expect(interaction.values.composerForm.draft).toEqual(draft)
    })

    it('runs an app command in the browser and clears the draft', async () => {
        setDraft('/good nice work')

        await expectLogic(logic, () => logic.actions.submitComposer()).toFinishAllListeners()

        await expectLogic(interaction).toNotHaveDispatchedActions(['submitComposerForm'])
        expect(interaction.values.composerForm.draft).toEqual('')
        expect(captureCommandFeedback).toHaveBeenCalledWith(
            'task-1',
            'trace-1',
            'good',
            { taskId: 'task-1', runId: 'run-1' },
            'nice work'
        )
    })

    it('keeps the draft and shows an error when a required argument is missing', async () => {
        setDraft('/feedback')

        await expectLogic(logic, () => logic.actions.submitComposer()).toFinishAllListeners()

        expect(interaction.values.composerForm.draft).toEqual('/feedback')
        expect(lemonToast.error).toHaveBeenCalled()
        expect(captureCommandFeedback).not.toHaveBeenCalled()
        await expectLogic(interaction).toNotHaveDispatchedActions(['submitComposerForm'])
    })

    it('asks a side question out of band and shows the answer', async () => {
        ;(tasksRunsCommandCreate as jest.Mock).mockResolvedValue({
            jsonrpc: '2.0',
            result: { answer: 'It is a funnel.' },
        })
        setDraft('/btw what is this?')

        await expectLogic(logic, () => logic.actions.submitComposer()).toFinishAllListeners()

        expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'task-1', 'run-1', {
            jsonrpc: '2.0',
            method: 'side_question',
            params: { question: 'what is this?' },
        })
        expect(logic.values.commandResult).toEqual({ title: 'what is this?', body: 'It is a funnel.' })
    })

    it('offers /btw only on a live Claude run', async () => {
        expect(logic.values.slashCommands.map((c) => c.name)).toContain('btw')

        await expectLogic(logic, () => (interaction.actions as any).setStubTerminal(true)).toFinishAllListeners()

        expect(logic.values.slashCommands.map((c) => c.name)).not.toContain('btw')
    })
})
