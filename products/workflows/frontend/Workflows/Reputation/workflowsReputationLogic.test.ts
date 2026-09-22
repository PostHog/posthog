import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { workflowsReputationLogic } from './workflowsReputationLogic'

const response = (suspended: boolean): TeamEmailReputationResponseApi =>
    ({
        aws: { health: 'healthy', sending_status: 'ENABLED', findings: [] },
        reputation: null,
        workflows: [],
        isps: [],
        isp_shared_domains: [],
        isp_withheld_domains: [],
        sending_allowance: null,
        email_sending_suspended: suspended,
        email_sending_suspended_at: suspended ? '2026-09-01T00:00:00Z' : null,
        email_sending_suspension_reason: suspended ? 'Spam complaint rate above 0.5%' : '',
    }) as unknown as TeamEmailReputationResponseApi

describe('workflowsReputationLogic', () => {
    let logic: ReturnType<typeof workflowsReputationLogic.build>
    let capture: jest.SpyInstance

    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/reputation': response(true) } })
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        logic = workflowsReputationLogic()
        logic.mount()
    })

    afterEach(() => {
        capture.mockRestore()
        logic.unmount()
    })

    const shownEvents = (): unknown[] =>
        capture.mock.calls.filter(([event]) => event === 'workflow email suspension banner shown')

    it('reports the banner once per suspension episode, not once per reload', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(shownEvents()).toHaveLength(1)

        // A search keystroke reloads the same suspended response.
        logic.actions.loadReputationSuccess(response(true))
        expect(shownEvents()).toHaveLength(1)

        logic.actions.loadReputationSuccess(response(false))
        logic.actions.loadReputationSuccess(response(true))
        expect(shownEvents()).toHaveLength(2)
    })
})
