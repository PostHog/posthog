import { initKeaTests } from '~/test/init'

import type { AgentContextItem } from '../types/contextTypes'
import { runContextLogic } from './runContextLogic'

const dashboard: AgentContextItem = { type: 'dashboard', id: 1, name: 'Growth' }
const insight: AgentContextItem = { type: 'insight', id: 'abc', name: 'Signups' }
const text = (value: string): AgentContextItem => ({ type: 'text', value })

describe('runContextLogic', () => {
    let logic: ReturnType<typeof runContextLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = runContextLogic({ streamKey: 'conv-1' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('merges every source into one list and dedupes entities across sources by key', () => {
        logic.actions.registerContextSource('scene', [dashboard, insight])
        // A second source re-supplies the same dashboard (by type+id) — it must not appear twice.
        logic.actions.registerContextSource('other', [{ type: 'dashboard', id: 1, name: 'Growth (stale)' }])

        expect(logic.values.attachedContext).toEqual([dashboard, insight])
    })

    it('never dedupes text items — repeated text from different sources all pass through', () => {
        logic.actions.registerContextSource('a', [text('note one')])
        logic.actions.registerContextSource('b', [text('note one')])

        expect(logic.values.attachedContext).toEqual([text('note one'), text('note one')])
    })

    it('drops a source’s items when it deregisters, leaving the others intact', () => {
        logic.actions.registerContextSource('scene', [dashboard])
        logic.actions.registerContextSource('imperative-src', [insight])
        logic.actions.deregisterContextSource('scene')

        expect(logic.values.attachedContext).toEqual([insight])
    })

    it('replaces a source’s bucket wholesale on re-register (idempotent), not appends', () => {
        logic.actions.registerContextSource('scene', [dashboard, insight])
        logic.actions.registerContextSource('scene', [dashboard])

        expect(logic.values.attachedContext).toEqual([dashboard])
    })

    it('attaches and detaches imperative items, deduping entities but not text', () => {
        logic.actions.attach(dashboard)
        logic.actions.attach(dashboard) // dup entity — ignored
        logic.actions.attach(text('hi'))
        logic.actions.attach(text('hi')) // dup text — kept

        expect(logic.values.attachedContext).toEqual([dashboard, text('hi'), text('hi')])

        logic.actions.detach('dashboard:1')
        expect(logic.values.attachedContext).toEqual([text('hi'), text('hi')])
    })

    it('clear removes every source and imperative item', () => {
        logic.actions.registerContextSource('scene', [dashboard])
        logic.actions.attach(insight)
        logic.actions.clear()

        expect(logic.values.attachedContext).toEqual([])
    })
})
