import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { issueActionsLogic } from './issueActionsLogic'

describe('issueActionsLogic', () => {
    let logic: ReturnType<typeof issueActionsLogic.build>

    beforeEach(() => {
        useMocks({
            patch: {
                '/api/environments/:team_id/error_tracking/issues/:id/': { status: 'resolved' },
            },
        })
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
        logic = issueActionsLogic()
        logic.mount()
    })

    afterEach(() => logic?.unmount())

    it('celebrates once a resolve succeeds, not when it is requested', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateIssueStatus('issue-1', 'resolved')
        })
            .toDispatchActions(['mutationStart', 'celebrateResolve', 'mutationSuccess'])
            .toMatchValues({ resolveCelebrationNonce: 1 })
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('does not celebrate when a resolve fails, and surfaces an error toast', async () => {
        useMocks({
            patch: {
                '/api/environments/:team_id/error_tracking/issues/:id/': () => [500, { detail: 'nope' }],
            },
        })
        await expectLogic(logic, () => {
            logic.actions.updateIssueStatus('issue-1', 'resolved')
        })
            .toDispatchActions(['mutationStart', 'mutationFailure'])
            .toNotHaveDispatchedActions(['celebrateResolve'])
            .toMatchValues({ resolveCelebrationNonce: 0 })
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('does not celebrate when an issue is reopened', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateIssueStatus('issue-1', 'active')
        })
            .toDispatchActions(['mutationSuccess'])
            .toNotHaveDispatchedActions(['celebrateResolve'])
            .toMatchValues({ resolveCelebrationNonce: 0 })
    })

    it('tracks in-flight mutations so the trigger can show a loading state', async () => {
        await expectLogic(logic, () => {
            logic.actions.mutationStart('updateIssueStatus')
        }).toMatchValues({ pendingMutations: { updateIssueStatus: 1 } })

        await expectLogic(logic, () => {
            logic.actions.mutationSuccess('updateIssueStatus')
        }).toMatchValues({ pendingMutations: { updateIssueStatus: 0 } })
    })
})
