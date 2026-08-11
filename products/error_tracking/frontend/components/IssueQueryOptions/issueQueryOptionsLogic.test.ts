import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { issueQueryOptionsLogic } from './issueQueryOptionsLogic'

const LOGIC_KEY = 'test'
const PERSISTED_STATUS_KEY = `products.error_tracking.components.IssueQueryOptions.issueQueryOptionsLogic.${LOGIC_KEY}.status`

describe('issueQueryOptionsLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    // Values are read from persistence when the logic is built, so build after seeding localStorage
    const mountLogic = (): ReturnType<typeof issueQueryOptionsLogic.build> => {
        const logic = issueQueryOptionsLogic({ logicKey: LOGIC_KEY })
        logic.mount()
        return logic
    }

    it.each(['open', 'new', 'pending', 'pending_release', 'archived'])(
        'falls back to the default status when setStatus receives %p',
        (status) => {
            const logic = mountLogic()
            logic.actions.setStatus(status as 'active')
            expect(logic.values.status).toBe('active')
        }
    )

    it.each(['all', 'resolved', 'suppressed'] as const)('applies the valid status %p', (status) => {
        const logic = mountLogic()
        logic.actions.setStatus(status)
        expect(logic.values.status).toBe(status)
    })

    it('applies a valid status from the URL', () => {
        const logic = mountLogic()
        router.actions.push('/error_tracking', { status: 'resolved' })
        expect(logic.values.status).toBe('resolved')
    })

    it.each([['open'], [''], [null]])(
        'falls back to the default when the URL has invalid status %p, overriding the persisted one',
        (param) => {
            localStorage.setItem(PERSISTED_STATUS_KEY, JSON.stringify('resolved'))
            const logic = mountLogic()
            router.actions.push('/error_tracking', { status: param })
            expect(logic.values.status).toBe('active')
        }
    )

    it('resets an invalid persisted status on mount', () => {
        localStorage.setItem(PERSISTED_STATUS_KEY, JSON.stringify('open'))
        const logic = mountLogic()
        expect(logic.values.status).toBe('active')
    })

    it('keeps a valid persisted status on mount', () => {
        localStorage.setItem(PERSISTED_STATUS_KEY, JSON.stringify('resolved'))
        const logic = mountLogic()
        expect(logic.values.status).toBe('resolved')
    })
})
