import { expectLogic } from 'kea-test-utils'

import { fetchIntegrationAssignees } from 'lib/integrations/integrationAssignees'

import { initKeaTests } from '~/test/init'

import { externalIssueAssigneesLogic } from './externalIssueAssigneesLogic'

jest.mock('lib/integrations/integrationAssignees', () => ({
    fetchIntegrationAssignees: jest.fn(),
}))

const USERS = [{ id: 'u1', name: 'Ada' }]

const mockFetchAssignees = jest.mocked(fetchIntegrationAssignees)

describe('externalIssueAssigneesLogic', () => {
    let logic: ReturnType<typeof externalIssueAssigneesLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockFetchAssignees.mockReset().mockResolvedValue({ users: USERS, reconnect_required: false })
    })

    afterEach(() => logic?.unmount())

    it('loads assignees for the chosen integration and scope on mount', async () => {
        logic = externalIssueAssigneesLogic({ integrationId: 1, kind: 'jira', scope: 'ENG' })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadAssigneesSuccess'])
            .toMatchValues({
                assignees: { users: USERS, reconnect_required: false },
            })
        expect(mockFetchAssignees).toHaveBeenCalledWith(expect.any(String), {
            integrationId: 1,
            kind: 'jira',
            scope: 'ENG',
            search: '',
        })
    })

    it('keeps the reconnect flag so the field can ask for a reconnect', async () => {
        mockFetchAssignees.mockResolvedValue({ users: [], reconnect_required: true })
        logic = externalIssueAssigneesLogic({ integrationId: 1, kind: 'jira', scope: 'ENG' })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadAssigneesSuccess'])
            .toMatchValues({
                assignees: { users: [], reconnect_required: true },
            })
    })

    it('searches once the user stops typing, with the latest input', async () => {
        jest.useFakeTimers()
        try {
            logic = externalIssueAssigneesLogic({ integrationId: 1, kind: 'gitlab', scope: null })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadAssigneesSuccess'])
            mockFetchAssignees.mockClear()

            logic.actions.setSearch('a')
            logic.actions.setSearch('ad')
            jest.advanceTimersByTime(300)

            await expectLogic(logic).toDispatchActions(['loadAssigneesSuccess'])
            expect(mockFetchAssignees).toHaveBeenCalledTimes(1)
            expect(mockFetchAssignees).toHaveBeenCalledWith(expect.any(String), {
                integrationId: 1,
                kind: 'gitlab',
                scope: null,
                search: 'ad',
            })
        } finally {
            jest.useRealTimers()
        }
    })

    it('leaves assignees unresolved when the lookup fails', async () => {
        mockFetchAssignees.mockRejectedValue(new Error('boom'))
        logic = externalIssueAssigneesLogic({ integrationId: 1, kind: 'gitlab', scope: null })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadAssigneesFailure']).toMatchValues({
            assignees: null,
            assigneesLoading: false,
        })
    })
})
