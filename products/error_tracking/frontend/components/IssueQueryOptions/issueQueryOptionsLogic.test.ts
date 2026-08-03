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

    it.each(['open', 'new', 'pending'])('falls back to the default status when setStatus receives %p', (status) => {
        const logic = mountLogic()
        logic.actions.setStatus(status as 'active')
        expect(logic.values.status).toBe('active')
    })

    it.each(['all', 'resolved', 'suppressed', 'pending_release', 'archived'] as const)(
        'applies the valid status %p',
        (status) => {
            const logic = mountLogic()
            logic.actions.setStatus(status)
            expect(logic.values.status).toBe(status)
        }
    )

    it.each([
        ['open', 'active'],
        ['resolved', 'resolved'],
    ])('URL param status=%p results in status %p', (param, expected) => {
        const logic = mountLogic()
        router.actions.push('/error_tracking', { status: param })
        expect(logic.values.status).toBe(expected)
    })

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
