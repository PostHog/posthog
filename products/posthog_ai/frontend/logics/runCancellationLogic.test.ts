import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import { tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'

import type { StoredLogEntry } from '../types/wireTypes'
import { runCancellationLogic } from './runCancellationLogic'
import { runStreamLogic } from './runStreamLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({ tasksRunsCommandCreate: jest.fn() }))

function ready(runId = 'run-1'): StoredLogEntry {
    return {
        type: 'notification',
        source_run_id: runId,
        notification: {
            method: '_posthog/progress',
            params: { group: `setup:${runId}`, step: 'agent', status: 'completed' },
        },
    }
}

function prompt(runId = 'run-1', sessionUpdate = 'user_message_chunk'): StoredLogEntry {
    return {
        type: 'notification',
        source_run_id: runId,
        notification: {
            method: 'session/update',
            params: {
                update: { sessionUpdate, content: { type: 'text', text: 'A synthetic task' } },
            },
        },
    }
}

describe('runCancellationLogic', () => {
    let logic: ReturnType<typeof runCancellationLogic.build>
    let stream: ReturnType<typeof runStreamLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(tasksRunsCommandCreate).mockReset().mockResolvedValue({ jsonrpc: '2.0', result: {} })
        jest.spyOn(api.tasks.runs, 'openStream').mockImplementation(() => new Promise(() => {}))
        jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
        logic = runCancellationLogic({ streamKey: 'draft-1' })
        logic.mount()
        stream = runStreamLogic({ streamKey: 'draft-1' })
        stream.actions.startOptimisticRun('A synthetic task')
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    const attach = (runId = 'run-1'): void => {
        stream.actions.bootstrapRun({ taskId: 'task-1', runId, justCreatedRun: true })
    }

    it.each([
        ['before attachment', 'user_message_chunk'],
        ['while starting', 'user_message_chunk'],
        ['already ready', 'user_message_chunk'],
        ['while starting', 'user_message'],
        ['while starting', 'agent_message'],
    ])('stops the same run once when requested %s with %s', async (phase, sessionUpdate) => {
        if (phase !== 'before attachment') {
            attach()
        }
        if (phase === 'already ready') {
            stream.actions.ingestAcpFrame(ready())
            stream.actions.ingestAcpFrame(prompt('run-1', sessionUpdate))
        }
        logic.actions.requestCancellation()
        logic.actions.requestCancellation()
        if (phase !== 'already ready') {
            expect(logic.values.cancellationState).toBe('waiting')
            expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        }
        if (phase === 'before attachment') {
            attach()
        }
        await expectLogic(logic, () => {
            stream.actions.ingestAcpFrame(ready())
            expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(phase === 'already ready' ? 1 : 0)
            stream.actions.ingestAcpFrame(prompt('run-1', sessionUpdate))
        }).toFinishAllListeners()
        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
        expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'task-1', 'run-1', {
            jsonrpc: '2.0',
            method: 'cancel',
        })
        expect(logic.values.cancellationState).toBe('sending')
        stream.actions.ingestAcpFrame({
            type: 'notification',
            source_run_id: 'run-1',
            notification: { method: '_posthog/turn_complete' },
        })
        expect(logic.values.cancellationState).toBeNull()
    })

    it('ignores readiness from an earlier resumed run', async () => {
        attach()
        logic.actions.requestCancellation()
        await expectLogic(logic, () =>
            stream.actions.ingestAcpFrame(ready('previous-run'), 'replay')
        ).toFinishAllListeners()
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.cancellationState).toBe('waiting')
        await expectLogic(logic, () => {
            stream.actions.ingestAcpFrame(ready())
            stream.actions.ingestAcpFrame(prompt('previous-run'), 'replay')
        }).toFinishAllListeners()
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        await expectLogic(logic, () => stream.actions.ingestAcpFrame(prompt())).toFinishAllListeners()
        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
    })

    it.each(['leave', 'switch', 'terminal', 'reset', 'unmount'])('clears a waiting stop on %s', async (transition) => {
        attach()
        logic.actions.requestCancellation()
        if (transition === 'leave') {
            logic.actions.clearCancellation()
        } else if (transition === 'switch') {
            attach('run-2')
        } else if (transition === 'terminal') {
            stream.actions.handleTerminalStatus({ status: 'failed' })
        } else if (transition === 'reset') {
            stream.actions.reset()
        } else {
            logic.unmount()
            logic.mount()
            attach()
        }
        await expectLogic(logic, () => {
            stream.actions.ingestAcpFrame(ready(transition === 'switch' ? 'run-2' : 'run-1'))
            stream.actions.ingestAcpFrame(prompt(transition === 'switch' ? 'run-2' : 'run-1'))
        }).toFinishAllListeners()
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.cancellationState).toBeNull()
    })

    it.each(['network', 'agent'])('allows retry after a %s cancellation error', async (failure) => {
        attach()
        stream.actions.ingestAcpFrame(ready())
        stream.actions.ingestAcpFrame(prompt())
        if (failure === 'network') {
            jest.mocked(tasksRunsCommandCreate).mockRejectedValueOnce(new Error('Network unavailable'))
        } else {
            jest.mocked(tasksRunsCommandCreate).mockResolvedValueOnce({
                jsonrpc: '2.0',
                error: { code: -32000, message: 'Agent unavailable' },
            })
        }
        await expectLogic(logic, () => logic.actions.requestCancellation()).toFinishAllListeners()
        expect(logic.values.cancellationState).toBeNull()
        expect(lemonToast.error).toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.requestCancellation()).toFinishAllListeners()
        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(2)
        expect(logic.values.cancellationState).toBe('sending')
    })
})
