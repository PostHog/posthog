import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { attachedContextLogic } from './attachedContextLogic'

describe('attachedContextLogic', () => {
    let logic: ReturnType<typeof attachedContextLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = attachedContextLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('registers and upserts a provider, and deregisters it', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerContext('scene', [{ type: 'insight', key: 'a', label: 'A' }])
        }).toMatchValues({ contextItems: [{ type: 'insight', key: 'a', label: 'A' }], hasContext: true })

        // Re-register the same provider replaces its items (upsert).
        await expectLogic(logic, () => {
            logic.actions.registerContext('scene', [{ type: 'dashboard', key: 1 }])
        }).toMatchValues({ contextItems: [{ type: 'dashboard', key: 1 }] })

        await expectLogic(logic, () => {
            logic.actions.deregisterContext('scene')
        }).toMatchValues({ contextItems: [], hasContext: false })
    })

    it('dedupes across providers by `${type}:${key ?? value}` (first writer wins)', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerContext('p1', [{ type: 'insight', key: 'x', label: 'first' }])
            logic.actions.registerContext('p2', [
                { type: 'insight', key: 'x', label: 'second' },
                { type: 'dashboard', key: 9 },
            ])
        }).toMatchValues({
            contextItems: [
                { type: 'insight', key: 'x', label: 'first' },
                { type: 'dashboard', key: 9 },
            ],
        })
    })

    it('drops items with neither key nor value', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerContext('p', [{ type: 'insight' }, { type: 'text', value: 'keep me' }])
        }).toMatchValues({ contextItems: [{ type: 'text', value: 'keep me' }] })
    })

    // Sent-context keys are scoped per task: a global (unkeyed) store would prune context from the first
    // message of an unrelated task just because the same resource was sent from another one.
    it('accumulates sent context keys per task without leaking across tasks', async () => {
        await expectLogic(logic, () => {
            logic.actions.markContextSent('task-a', ['insight:x'])
            logic.actions.markContextSent('task-a', ['insight:x', 'dashboard:9'])
            logic.actions.markContextSent('task-b', ['insight:x'])
        }).toMatchValues({
            sentContextKeysByTask: {
                'task-a': ['insight:x', 'dashboard:9'],
                'task-b': ['insight:x'],
            },
        })
    })
})
