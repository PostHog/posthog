import { actions, kea, key, path, props, reducers } from 'kea'

import { initKeaTests } from '~/test/init'

import { retainMountedLogic } from './retainedLogics'

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
    })
})
