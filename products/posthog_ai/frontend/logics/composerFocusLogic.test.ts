import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import type { ComposerFocus } from '../types/composerFocusTypes'
import { attachedContextLogic } from './attachedContextLogic'
import { composerFocusLogic } from './composerFocusLogic'

describe('composerFocusLogic', () => {
    let logic: ReturnType<typeof composerFocusLogic.build>

    const focus = (id: string, overrides: Partial<ComposerFocus> = {}): ComposerFocus => ({
        id,
        title: `Cell ${id}`,
        ...overrides,
    })

    beforeEach(() => {
        initKeaTests()
        logic = composerFocusLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('registers, upserts and deregisters a provider', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerFocus('notebook', focus('a'))
        }).toMatchValues({ focus: expect.objectContaining({ id: 'a', providerId: 'notebook' }) })

        await expectLogic(logic, () => {
            logic.actions.registerFocus('notebook', focus('b'))
        }).toMatchValues({ providers: { notebook: expect.objectContaining({ id: 'b' }) } })

        await expectLogic(logic, () => {
            logic.actions.deregisterFocus('notebook')
        }).toMatchValues({ focus: null })
    })

    it('shows the most recent registration, including a re-registered earlier provider', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerFocus('first', focus('a'))
            logic.actions.registerFocus('second', focus('b'))
        }).toMatchValues({ focus: expect.objectContaining({ providerId: 'second' }) })

        await expectLogic(logic, () => {
            logic.actions.registerFocus('first', focus('c'))
        }).toMatchValues({ focus: expect.objectContaining({ providerId: 'first', id: 'c' }) })

        // Dropping the newest one falls back to the one below it rather than to nothing.
        await expectLogic(logic, () => {
            logic.actions.deregisterFocus('first')
        }).toMatchValues({ focus: expect.objectContaining({ providerId: 'second' }) })
    })

    it('closing the card drops the focus and dismisses its context group', async () => {
        const contextLogic = attachedContextLogic()
        contextLogic.mount()
        logic.actions.registerFocus('notebook', focus('a', { dismissGroup: 'notebook-analyze-cell' }))

        await expectLogic(logic, () => {
            logic.actions.closeFocus('notebook')
        })
            .toDispatchActions(['closeFocus', 'deregisterFocus', 'dismissContext'])
            .toMatchValues({ focus: null })
        expect(contextLogic.values.dismissedGroups).toEqual({ 'notebook-analyze-cell': true })

        contextLogic.unmount()
    })
})
