import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { issueQueryOptionsLogic } from './issueQueryOptionsLogic'

const LOGIC_KEY = 'test'

describe('issueQueryOptionsLogic', () => {
    let logic: ReturnType<typeof issueQueryOptionsLogic.build>

    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        window.localStorage.clear()
    })

    it('falls back to the default when set to an invalid orderBy', async () => {
        logic = issueQueryOptionsLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        await expectLogic(logic, () => {
            // e.g. a sort option that was removed; would otherwise fail the query
            logic.actions.setOrderBy('revenue' as any)
        }).toFinishAllListeners()

        expect(logic.values.orderBy).toBe('last_seen')
    })

    it('resets an invalid persisted orderBy on mount', async () => {
        // Seed localStorage the way kea-localstorage stores it: mount once, force a write,
        // then overwrite that exact key with an invalid value before remounting.
        logic = issueQueryOptionsLogic({ logicKey: LOGIC_KEY })
        logic.mount()
        logic.actions.setOrderBy('occurrences')
        const storageKey = Object.keys(window.localStorage).find(
            (key) => key.includes('issueQueryOptionsLogic') && key.endsWith('orderBy')
        )
        expect(storageKey).not.toBeUndefined()
        logic.unmount()

        window.localStorage.setItem(storageKey!, JSON.stringify('revenue'))

        logic = issueQueryOptionsLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        expect(logic.values.orderBy).toBe('last_seen')
    })
})
