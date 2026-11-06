import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { errorTrackingExternalReferencesSearchIssuesRetrieve } from '../generated/api'
import { externalIssueSearchLogic } from './externalIssueSearchLogic'

jest.mock('../generated/api', () => ({
    errorTrackingExternalReferencesSearchIssuesRetrieve: jest.fn(),
}))

const mockSearchIssues = jest.mocked(errorTrackingExternalReferencesSearchIssuesRetrieve)

const RECENT_ISSUES = [
    { id: 'ISS-1', title: 'First issue', url: 'https://example.com/ISS-1', external_context: { id: 'ISS-1' } },
    { id: 'ISS-2', title: 'Second issue', url: 'https://example.com/ISS-2', external_context: { id: 'ISS-2' } },
]

describe('externalIssueSearchLogic', () => {
    let logic: ReturnType<typeof externalIssueSearchLogic.build>

    beforeEach(async () => {
        initKeaTests()
        mockSearchIssues.mockResolvedValue({ issues: RECENT_ISSUES })
        logic = externalIssueSearchLogic({ integrationId: 1, requiresRepository: false })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['searchIssuesSuccess'])
        mockSearchIssues.mockClear()
    })

    afterEach(() => logic.unmount())

    it('only a genuine input clear refetches, not the clear caused by selecting an issue', async () => {
        // LemonInputSelect clears its input BEFORE it reports the selection, so the
        // blank inputChanged lands before issueSelected. It must not trigger a search
        // that replaces the results the selection was made from.
        await expectLogic(logic, () => {
            logic.actions.inputChanged('')
            logic.actions.issueSelected()
        }).toDispatchActions(['searchIssuesSuccess'])
        expect(mockSearchIssues).not.toHaveBeenCalled()
        expect(logic.values.results).toEqual(RECENT_ISSUES)

        // The suppression is consumed: the user clearing the search afterwards refetches.
        await expectLogic(logic, () => {
            logic.actions.inputChanged('')
        }).toDispatchActions(['searchIssuesSuccess'])
        expect(mockSearchIssues).toHaveBeenCalledTimes(1)
    })

    it('typing right after a selection does not suppress the next genuine clear', async () => {
        // Typing within the debounce cancels the selection-clear search before it can
        // consume the suppression, so the flag must be reset by the nonblank search.
        await expectLogic(logic, () => {
            logic.actions.inputChanged('')
            logic.actions.issueSelected()
            logic.actions.inputChanged('crash')
        }).toDispatchActions(['searchIssuesSuccess'])
        expect(mockSearchIssues).toHaveBeenCalledTimes(1)

        await expectLogic(logic, () => {
            logic.actions.inputChanged('')
        }).toDispatchActions(['searchIssuesSuccess'])
        expect(mockSearchIssues).toHaveBeenCalledTimes(2)
    })
})
