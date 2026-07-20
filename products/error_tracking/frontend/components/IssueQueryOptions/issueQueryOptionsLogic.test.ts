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
        // Discover the persisted storage key by mounting once, then reset the kea context so
        // the next mount re-hydrates from the seeded (invalid) value rather than reusing the
        // already-built logic.
        logic = issueQueryOptionsLogic({ logicKey: LOGIC_KEY })
        logic.mount()
        const storageKey = Object.keys(window.localStorage).find(
            (key) => key.includes('issueQueryOptionsLogic') && key.endsWith('orderBy')
        )
        expect(storageKey).not.toBeUndefined()
        logic.unmount()

        initKeaTests()
        // kea-localstorage reads/writes via property access, so seed the same way.
        ;(window.localStorage as any)[storageKey!] = JSON.stringify('revenue')

        logic = issueQueryOptionsLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        expect(logic.values.orderBy).toBe('last_seen')
    })
})
