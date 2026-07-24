import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { mcpGatewayAuditCountsRetrieve, mcpGatewayAuditList } from '../generated/api'
import type { MCPAuditEventApi } from '../generated/api.schemas'
import { gatewayAuditLogic } from './gatewayAuditLogic'

jest.mock('../generated/api', () => ({
    mcpGatewayAuditCountsRetrieve: jest.fn(),
    mcpGatewayAuditList: jest.fn(),
}))

const mockAuditCountsRetrieve = jest.mocked(mcpGatewayAuditCountsRetrieve)
const mockAuditList = jest.mocked(mcpGatewayAuditList)

function auditEvent(id: string): MCPAuditEventApi {
    return {
        id,
        created_at: '2026-07-24T00:00:00Z',
        server_name: 'Example server',
        tool_name: id,
        decision: 'auto',
        actor_user: null,
        actor_service_account: null,
        actor_label: 'member@example.com',
    }
}

describe('gatewayAuditLogic', () => {
    let logic: ReturnType<typeof gatewayAuditLogic.build>

    beforeEach(async () => {
        initKeaTests()
        mockAuditList.mockResolvedValue({ count: 0, results: [] })
        mockAuditCountsRetrieve.mockResolvedValue({ all: 0, agents: 0, approvals: 0, blocked: 0 })
        logic = gatewayAuditLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it('discards an earlier filter response that resolves after the latest one', async () => {
        const staleEvent = auditEvent('stale-agent-tool')
        const freshEvent = auditEvent('fresh-blocked-tool')
        let resolveStale: (value: Awaited<ReturnType<typeof mcpGatewayAuditList>>) => void = () => {}

        mockAuditList.mockReset()
        mockAuditList
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveStale = resolve
                    })
            )
            .mockResolvedValueOnce({ count: 1, results: [freshEvent] })

        await expectLogic(logic, () => {
            logic.actions.setQuickFilter('agents')
            logic.actions.setQuickFilter('blocked')
        }).toDispatchActions(['loadAuditSuccess'])

        expect(logic.values.quickFilter).toBe('blocked')
        expect(logic.values.auditResponse).toEqual({ count: 1, results: [freshEvent] })

        resolveStale({ count: 1, results: [staleEvent] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.auditResponse).toEqual({ count: 1, results: [freshEvent] })
    })

    it('refreshes count badges after a filter change', async () => {
        const refreshedCounts = { all: 4, agents: 3, approvals: 2, blocked: 1 }
        mockAuditCountsRetrieve.mockResolvedValue(refreshedCounts)

        await expectLogic(logic, () => {
            logic.actions.setQuickFilter('blocked')
        })
            .toFinishAllListeners()
            .toMatchValues({ counts: refreshedCounts })
    })

    it('discards an earlier count response that resolves after the latest one', async () => {
        const staleCounts = { all: 1, agents: 1, approvals: 0, blocked: 0 }
        const freshCounts = { all: 2, agents: 1, approvals: 0, blocked: 1 }
        let resolveStale: (value: Awaited<ReturnType<typeof mcpGatewayAuditCountsRetrieve>>) => void = () => {}

        mockAuditCountsRetrieve.mockReset()
        mockAuditCountsRetrieve
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveStale = resolve
                    })
            )
            .mockResolvedValueOnce(freshCounts)

        await expectLogic(logic, () => {
            logic.actions.setQuickFilter('agents')
            logic.actions.setQuickFilter('blocked')
        }).toDispatchActions(['loadCountsSuccess'])

        expect(logic.values.counts).toEqual(freshCounts)

        resolveStale(staleCounts)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.counts).toEqual(freshCounts)
    })
})
