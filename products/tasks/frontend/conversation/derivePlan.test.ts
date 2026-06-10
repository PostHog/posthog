import type { AcpMessage, PlanEntry } from './acp-types'
import { derivePlan, getPlanStats } from './derivePlan'

function entry(content: string, status: PlanEntry['status']): PlanEntry {
    return { content, status }
}

function planEvent(entries: PlanEntry[], ts = 0): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: {
            jsonrpc: '2.0',
            method: 'session/update',
            params: { sessionId: 'session-1', update: { sessionUpdate: 'plan', entries } },
        },
    }
}

function agentChunkEvent(text: string, ts = 0): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: {
            jsonrpc: '2.0',
            method: 'session/update',
            params: {
                sessionId: 'session-1',
                update: { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text } },
            },
        },
    }
}

function promptResponseEvent(stopReason: string | undefined, ts = 0): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: { jsonrpc: '2.0', id: 1, result: stopReason !== undefined ? { stopReason } : {} },
    }
}

function turnCompleteNotificationEvent(ts = 0): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: { jsonrpc: '2.0', method: '_posthog/turn_complete', params: { stopReason: 'end_turn' } },
    }
}

describe('derivePlan', () => {
    it('returns null when there are no events', () => {
        expect(derivePlan([])).toBeNull()
    })

    it('returns null when the latest plan has no entries', () => {
        expect(derivePlan([planEvent([])])).toBeNull()
    })

    it('returns the plan from an in-progress turn', () => {
        const entries = [entry('Set up schema', 'completed'), entry('Write tests', 'in_progress')]
        const plan = derivePlan([agentChunkEvent('working'), planEvent(entries)])
        expect(plan).not.toBeNull()
        expect(plan?.entries).toEqual(entries)
    })

    it('returns null when a prompt response with stopReason follows the plan', () => {
        const events = [planEvent([entry('Write tests', 'in_progress')]), promptResponseEvent('end_turn')]
        expect(derivePlan(events)).toBeNull()
    })

    it('returns null when a turn_complete notification follows the plan', () => {
        const events = [planEvent([entry('Write tests', 'in_progress')]), turnCompleteNotificationEvent()]
        expect(derivePlan(events)).toBeNull()
    })

    it('ignores responses without a stopReason when detecting turn end', () => {
        const events = [planEvent([entry('Write tests', 'in_progress')]), promptResponseEvent(undefined)]
        expect(derivePlan(events)?.entries).toHaveLength(1)
    })

    it('returns the plan emitted after the latest turn end', () => {
        const events = [
            promptResponseEvent('end_turn'),
            agentChunkEvent('new turn'),
            planEvent([entry('Refactor', 'in_progress')]),
        ]
        expect(derivePlan(events)?.entries).toEqual([entry('Refactor', 'in_progress')])
    })

    it('returns the latest plan when the stream contains multiple plans', () => {
        const events = [
            planEvent([entry('Step one', 'in_progress')]),
            agentChunkEvent('progress'),
            planEvent([entry('Step one', 'completed'), entry('Step two', 'in_progress')]),
        ]
        expect(derivePlan(events)?.entries).toEqual([entry('Step one', 'completed'), entry('Step two', 'in_progress')])
    })

    it('hides a stale plan even when later turns produced no plan', () => {
        const events = [
            planEvent([entry('Old step', 'in_progress')]),
            promptResponseEvent('end_turn'),
            agentChunkEvent('follow-up turn without a plan'),
        ]
        expect(derivePlan(events)).toBeNull()
    })

    describe('getPlanStats', () => {
        it.each([
            {
                name: 'all pending',
                entries: [entry('a', 'pending'), entry('b', 'pending')],
                expected: { completed: 0, total: 2, inProgressContent: undefined, allCompleted: false },
            },
            {
                name: 'mixed statuses',
                entries: [entry('a', 'completed'), entry('b', 'in_progress'), entry('c', 'pending')],
                expected: { completed: 1, total: 3, inProgressContent: 'b', allCompleted: false },
            },
            {
                name: 'all completed',
                entries: [entry('a', 'completed'), entry('b', 'completed')],
                expected: { completed: 2, total: 2, inProgressContent: undefined, allCompleted: true },
            },
            {
                name: 'missing status treated as not completed',
                entries: [entry('a', undefined), entry('b', 'completed')],
                expected: { completed: 1, total: 2, inProgressContent: undefined, allCompleted: false },
            },
            {
                name: 'failed entry counts as not completed',
                entries: [
                    entry('a', 'completed'),
                    { content: 'b', status: 'failed' } as unknown as PlanEntry,
                    entry('c', 'pending'),
                ],
                expected: { completed: 1, total: 3, inProgressContent: undefined, allCompleted: false },
            },
        ])('computes stats for $name', ({ entries, expected }) => {
            const stats = getPlanStats({ entries })
            expect(stats.completed).toBe(expected.completed)
            expect(stats.total).toBe(expected.total)
            expect(stats.inProgress?.content).toBe(expected.inProgressContent)
            expect(stats.allCompleted).toBe(expected.allCompleted)
        })

        it('picks the first in-progress entry when several are running', () => {
            const stats = getPlanStats({ entries: [entry('first', 'in_progress'), entry('second', 'in_progress')] })
            expect(stats.inProgress?.content).toBe('first')
        })
    })
})
