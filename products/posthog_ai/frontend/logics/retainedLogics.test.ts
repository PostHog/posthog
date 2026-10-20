import { actions, kea, key, path, props, reducers } from 'kea'

import { initKeaTests } from '~/test/init'

import { findRetainedLogicKey, RETAINED_RUN_STREAMS, resolveRunStreamKey, retainMountedLogic } from './retainedLogics'

const streamStandIn = kea([
    props({} as { streamKey: string; runId: string }),
    key((props) => props.streamKey),
    path((streamKey) => ['test', 'retainedLogics', 'stream', streamKey]),
    reducers(({ props }) => ({ bootstrappedRunId: [props.runId as string | null, {}] })),
])

const counterLogic = kea([
    props({} as { id: string }),
    key((props) => props.id),
    path((id) => ['test', 'retainedLogics', 'counter', id]),
    actions({ increment: true }),
    reducers({ count: [0, { increment: (state: number) => state + 1 }] }),
])

describe('retainMountedLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('keeps the logic and its state after its holder unmounts, and evicts the oldest past the limit', () => {
        const holderUnmount = counterLogic({ id: 'a' }).mount()
        expect(retainMountedLogic('test', 'a', counterLogic({ id: 'a' }), 2)).toBe(false)
        counterLogic({ id: 'a' }).actions.increment()
        holderUnmount()

        expect(counterLogic.findMounted({ id: 'a' })?.values.count).toBe(1)
        expect(retainMountedLogic('test', 'a', counterLogic({ id: 'a' }), 2)).toBe(true)

        retainMountedLogic('test', 'b', counterLogic({ id: 'b' }), 2)
        retainMountedLogic('test', 'a', counterLogic({ id: 'a' }), 2)
        retainMountedLogic('test', 'c', counterLogic({ id: 'c' }), 2)

        expect(counterLogic.findMounted({ id: 'b' })).toBeNull()
        expect(counterLogic.findMounted({ id: 'a' })?.values.count).toBe(1)
        expect(counterLogic.findMounted({ id: 'c' })).not.toBeNull()
        expect(findRetainedLogicKey('test', (logic) => logic.values.count === 1)).toBe('a')
        expect(findRetainedLogicKey('test', (logic) => logic.values.count === 2)).toBeNull()
    })

    it.each([
        { name: 'no key resolves to the continuation alias', runId: 'run-b', streamKey: undefined, expected: 'run-a' },
        {
            name: 'the run id resolves to the continuation alias',
            runId: 'run-b',
            streamKey: 'run-b',
            expected: 'run-a',
        },
        { name: 'an explicit other key is kept', runId: 'run-b', streamKey: 'client-key', expected: 'client-key' },
        { name: 'a run with no retained stream keeps its key', runId: 'run-c', streamKey: 'run-c', expected: 'run-c' },
    ])('$name', ({ runId, streamKey, expected }) => {
        retainMountedLogic(RETAINED_RUN_STREAMS, 'run-a', streamStandIn({ streamKey: 'run-a', runId: 'run-b' }), 3)

        expect(resolveRunStreamKey(runId, streamKey)).toBe(expected)
    })
})
