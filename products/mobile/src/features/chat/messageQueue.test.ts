import type { PendingAttachment } from './attachments/types'
import {
    canDrain,
    EMPTY_QUEUE,
    joinQueueAttachments,
    type QueueAction,
    type QueueState,
    queueActions,
    queueReducer,
    type SendGate,
    sendNowState,
    shouldQueue,
} from './messageQueue'

function apply(...actions: QueueAction[]): QueueState {
    return actions.reduce(queueReducer, EMPTY_QUEUE)
}

const IDLE: SendGate = { phase: 'idle', sending: false, decisionPending: false }

function file(name: string): PendingAttachment {
    return { id: name, uri: `file:///picked/${name}`, name, size: 1, contentType: 'text/plain', isImage: false }
}

describe('message queue', () => {
    test.each<[string, QueueAction[], QueueState['hold']]>([
        ['a new message lifts a Stop hold', [queueActions.hold('cancelled'), queueActions.enqueue('b')], null],
        [
            'a new message keeps a failed delivery on hold',
            [queueActions.hold('unconfirmed'), queueActions.enqueue('b')],
            'unconfirmed',
        ],
    ])('%s', (_, actions, hold) => {
        expect(apply(queueActions.enqueue('a'), ...actions).hold).toBe(hold)
    })

    it('restores a failed delivery in front of rows queued since, and holds it', () => {
        const taken = apply(queueActions.enqueue('first'), queueActions.enqueue('second')).rows
        const state = apply(queueActions.enqueue('typed during the send'), queueActions.restore(taken))
        expect(state.rows.map((row) => row.text)).toEqual(['first', 'second', 'typed during the send'])
        expect(state.hold).toBe('unconfirmed')
    })

    it('keeps each row with its files through a restore, joins them in queue order, and drops them with the row', () => {
        const taken = apply(
            queueActions.enqueue('first', [file('a.txt'), file('b.txt')]),
            queueActions.enqueue('second', [file('c.txt')])
        ).rows
        const restored = apply(queueActions.enqueue('typed during the send'), queueActions.restore(taken))
        expect(joinQueueAttachments(restored.rows).map((attachment) => attachment.name)).toEqual([
            'a.txt',
            'b.txt',
            'c.txt',
        ])

        const removed = queueReducer(restored, queueActions.remove(restored.rows[0]?.id ?? ''))
        expect(joinQueueAttachments(removed.rows).map((attachment) => attachment.name)).toEqual(['c.txt'])
    })

    it('drops the hold with the last removed row, so the next queue drains', () => {
        const queued = apply(queueActions.enqueue('a'), queueActions.hold('unconfirmed'))
        const emptied = queueReducer(queued, queueActions.remove(queued.rows[0]?.id ?? ''))
        expect(canDrain(IDLE, queueReducer(emptied, queueActions.enqueue('b')))).toBe(true)
    })

    test.each<[string, Partial<SendGate>, boolean]>([
        ['an idle run', {}, true],
        ['a working agent', { phase: 'working' }, false],
        ['a reconnecting stream', { phase: 'reconnecting' }, false],
        ['a send in flight', { sending: true }, false],
        ['a pending decision', { decisionPending: true }, false],
    ])('decides between draining and queueing for %s', (_, gate, drains) => {
        const queue = apply(queueActions.enqueue('a'))
        expect(canDrain({ ...IDLE, ...gate }, queue)).toBe(drains)
        expect(shouldQueue({ ...IDLE, ...gate }, EMPTY_QUEUE)).toBe(!drains)
    })

    it('does not drain a held queue, and queues behind it while idle', () => {
        const held = apply(queueActions.enqueue('a'), queueActions.hold('cancelled'))
        expect(canDrain(IDLE, held)).toBe(false)
        expect(shouldQueue(IDLE, held)).toBe(true)
    })

    test.each<[string, Parameters<typeof sendNowState>[0], ReturnType<typeof sendNowState>]>([
        [
            'a pending decision',
            { ...IDLE, decisionPending: true, canSteer: false, stopping: false },
            { pending: false, disabledReason: 'Answer the agent first' },
        ],
        [
            'a turn the agent has not started',
            { ...IDLE, phase: 'working', canSteer: false, stopping: false },
            { pending: false, disabledReason: 'Wait for the agent to start' },
        ],
        ['a steerable turn', { ...IDLE, phase: 'working', canSteer: true, stopping: false }, { pending: false }],
        ['a Stop in flight', { ...IDLE, phase: 'working', canSteer: false, stopping: true }, { pending: true }],
        ['an idle run', { ...IDLE, canSteer: false, stopping: false }, { pending: false }],
    ])('sets Send now for %s', (_, gate, expected) => {
        expect(sendNowState(gate)).toEqual(expected)
    })
})
