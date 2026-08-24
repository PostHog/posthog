import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { issueQueryOptionsLogic } from './issueQueryOptionsLogic'

const LOGIC_KEY = 'test'
const PERSISTED_KEY_PREFIX = `products.error_tracking.components.IssueQueryOptions.issueQueryOptionsLogic.${LOGIC_KEY}`
const PERSISTED_STATUS_KEY = `${PERSISTED_KEY_PREFIX}.status`
const PERSISTED_ASSIGNEE_KEY = `${PERSISTED_KEY_PREFIX}.assignee`

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

    // A malformed assignee reaches the query, which the backend rejects with a 400. It renders as
    // unset, and it's persisted, so the whole issues page keeps failing until it's manually cleared.
    const MALFORMED_ASSIGNEES = [
        'me',
        7,
        { type: 'user' },
        { type: 'user', id: null },
        { type: 'user', id: '' },
        { type: 'user', id: '7' },
        { type: 'user', id: 1.5 },
        { type: 'role', id: 7 },
        { type: 'role', id: 'not-a-uuid' },
        { type: 'role', id: '  ' },
        { type: 'team', id: 7 },
        { id: 7 },
        ['role:01978cae-04b5-0000-17fb-0405fcb791be'],
    ]

    it.each(MALFORMED_ASSIGNEES)('falls back to no assignee when setAssignee receives %p', (assignee) => {
        const logic = mountLogic()
        logic.actions.setAssignee(assignee as any)
        expect(logic.values.assignee).toBeNull()
    })

    it.each([
        { type: 'user', id: 7 },
        { type: 'role', id: '01978cae-04b5-0000-17fb-0405fcb791be' },
    ] as const)('applies the valid assignee %p', (assignee) => {
        const logic = mountLogic()
        logic.actions.setAssignee(assignee)
        expect(logic.values.assignee).toEqual(assignee)
    })

    it('drops fields the query schema does not accept', () => {
        const logic = mountLogic()
        logic.actions.setAssignee({ type: 'user', id: 7, user: { first_name: 'Someone' } } as any)
        expect(logic.values.assignee).toEqual({ type: 'user', id: 7 })
    })

    it.each(MALFORMED_ASSIGNEES)('resets the malformed persisted assignee %p on mount', (assignee) => {
        localStorage.setItem(PERSISTED_ASSIGNEE_KEY, JSON.stringify(assignee))
        const logic = mountLogic()
        expect(logic.values.assignee).toBeNull()
    })

    it('keeps a valid persisted assignee on mount', () => {
        localStorage.setItem(PERSISTED_ASSIGNEE_KEY, JSON.stringify({ type: 'user', id: 7 }))
        const logic = mountLogic()
        expect(logic.values.assignee).toEqual({ type: 'user', id: 7 })
    })

    it('falls back to no assignee when the URL has a malformed one, overriding the persisted one', () => {
        localStorage.setItem(PERSISTED_ASSIGNEE_KEY, JSON.stringify({ type: 'user', id: 7 }))
        const logic = mountLogic()
        router.actions.push('/error_tracking', { assignee: 'me' })
        expect(logic.values.assignee).toBeNull()
    })
})
