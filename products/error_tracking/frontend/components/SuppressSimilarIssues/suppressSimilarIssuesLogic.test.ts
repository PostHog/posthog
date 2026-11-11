import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { errorTrackingSuppressionRulesCreate } from '../../generated/api'
import { issueActionsLogic } from '../IssueActions/issueActionsLogic'
import { suppressSimilarIssuesLogic } from './suppressSimilarIssuesLogic'

jest.mock('../../generated/api', () => ({
    errorTrackingSuppressionRulesCreate: jest.fn(),
}))

const mockSuppressionRulesCreate = jest.mocked(errorTrackingSuppressionRulesCreate)

const CHILD_ENVIRONMENT: TeamType = { ...MOCK_DEFAULT_TEAM, id: MOCK_TEAM_ID + 1, project_id: MOCK_TEAM_ID }

describe('suppressSimilarIssuesLogic', () => {
    let logic: ReturnType<typeof suppressSimilarIssuesLogic.build>

    beforeEach(() => {
        initKeaTests(true, CHILD_ENVIRONMENT)
        jest.spyOn(api.errorTracking, 'updateIssue').mockResolvedValue({} as never)
        jest.spyOn(api.errorTracking, 'bulkMarkStatus').mockResolvedValue({} as never)
        jest.spyOn(api, 'query').mockResolvedValue({ results: [[0, 0]] } as never)
        mockSuppressionRulesCreate.mockResolvedValue({} as never)
        logic = suppressSimilarIssuesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('creates rules in the current environment, not in its parent project', async () => {
        logic.actions.openSuggestion([
            { id: 'issue-1', exceptionType: 'Error', exceptionMessage: 'Request failed with status code 503' },
        ])

        await expectLogic(logic, () => {
            logic.actions.createRules()
        }).toDispatchActions(['createRulesSuccess'])

        expect(mockSuppressionRulesCreate).toHaveBeenCalledWith(
            String(CHILD_ENVIRONMENT.id),
            expect.objectContaining({ sampling_rate: 1 })
        )
    })

    it.each(['single', 'bulk'] as const)(
        'opens after %s suppression before the message query returns',
        async (mode) => {
            let finishQuery!: (response: { results: [string, string, string][] }) => void
            jest.spyOn(api, 'queryHogQL').mockImplementation(
                () =>
                    new Promise((resolve) => {
                        finishQuery = resolve
                    }) as never
            )

            await expectLogic(logic, () => {
                if (mode === 'single') {
                    issueActionsLogic.actions.updateIssueStatus('issue-1', 'suppressed')
                } else {
                    issueActionsLogic.actions.suppressIssues(['issue-1'])
                }
            }).toDispatchActions(['loadSnapshots'])

            expect(logic.values.isOpen).toBe(true)
            expect(logic.values.snapshotsLoading).toBe(true)
            expect(logic.values.selectedOption).toBeNull()

            await expectLogic(logic, () => {
                finishQuery({ results: [['issue-1', '["Error"]', '["Network error"]']] })
            }).toDispatchActions(['openSuggestion'])

            expect(logic.values.snapshotsLoading).toBe(false)
            expect(logic.values.scopeOptions.map((option) => option.key)).toEqual(['exact'])
            expect(logic.values.selectedScope).toBe('exact')
        }
    )

    it('does not reopen a dismissed dialog when the message query returns', async () => {
        let finishQuery!: (response: { results: [string, string, string][] }) => void
        jest.spyOn(api, 'queryHogQL').mockImplementation(
            () =>
                new Promise((resolve) => {
                    finishQuery = resolve
                }) as never
        )
        logic.actions.loadSnapshots(['issue-1'])
        logic.actions.dismissSuggestion()

        await expectLogic(logic, () => {
            finishQuery({ results: [['issue-1', '["Error"]', '["Timeout after 3000ms"]']] })
        }).toDispatchActions(['loadSnapshotsSuccess'])

        expect(logic.values.isOpen).toBe(false)
    })

    it('keeps a newer dialog open when an older message query fails', async () => {
        let rejectFirstQuery!: (error: Error) => void
        jest.spyOn(api, 'queryHogQL')
            .mockImplementationOnce(
                () =>
                    new Promise((_, reject) => {
                        rejectFirstQuery = reject
                    }) as never
            )
            .mockResolvedValueOnce({ results: [['issue-2', '["Error"]', '["Network error"]']] } as never)
        logic.actions.loadSnapshots(['issue-1'])
        logic.actions.dismissSuggestion()

        await expectLogic(logic, () => {
            logic.actions.loadSnapshots(['issue-2'])
        }).toDispatchActions(['openSuggestion'])

        await expectLogic(logic, () => {
            rejectFirstQuery(new Error('Message query failed'))
        }).toFinishAllListeners()

        expect(logic.values.isOpen).toBe(true)
        expect(logic.values.snapshots[0].id).toBe('issue-2')
    })

    it('closes when the issue has no exception message', async () => {
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [['issue-1', '["Error"]', '[]']] } as never)

        await expectLogic(logic, () => {
            logic.actions.loadSnapshots(['issue-1'])
        }).toDispatchActions(['closeSuggestion'])

        expect(logic.values.isOpen).toBe(false)
        expect(logic.values.selectedOption).toBeNull()
    })

    it('does not offer suppression rules when the status update fails', async () => {
        jest.spyOn(api.errorTracking, 'updateIssue').mockRejectedValue(new Error('Status update failed'))
        const query = jest.spyOn(api, 'queryHogQL')

        await expectLogic(issueActionsLogic, () => {
            issueActionsLogic.actions.updateIssueStatus('issue-1', 'suppressed')
        }).toDispatchActions(['mutationFailure'])

        expect(logic.values.isOpen).toBe(false)
        expect(query).not.toHaveBeenCalled()
    })
})
