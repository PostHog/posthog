import { MOCK_DEFAULT_BASIC_USER } from '~/lib/api.mock'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    mcpGatewayConfigList,
    mcpGatewayMembersList,
    mcpGatewayMembersRetrieve,
    mcpGatewayRulesList,
    mcpGatewayServersList,
    mcpGatewayServiceAccountsList,
} from '../generated/api'
import type { GatewayMemberSummaryApi } from '../generated/api.schemas'
import { gatewayMemberLogic } from './gatewayMemberLogic'
import { mcpGatewayLogic } from './mcpGatewayLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayMembersRetrieve: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
}))

const mockConfigList = jest.mocked(mcpGatewayConfigList)
const mockMembersList = jest.mocked(mcpGatewayMembersList)
const mockMemberRetrieve = jest.mocked(mcpGatewayMembersRetrieve)
const mockRulesList = jest.mocked(mcpGatewayRulesList)
const mockServersList = jest.mocked(mcpGatewayServersList)
const mockServiceAccountsList = jest.mocked(mcpGatewayServiceAccountsList)

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

function gatewayMember(): GatewayMemberSummaryApi {
    return {
        user: {
            id: MOCK_DEFAULT_BASIC_USER.id,
            uuid: MOCK_DEFAULT_BASIC_USER.uuid,
            distinct_id: MOCK_DEFAULT_BASIC_USER.distinct_id,
            first_name: MOCK_DEFAULT_BASIC_USER.first_name,
            email: MOCK_DEFAULT_BASIC_USER.email,
            hedgehog_config: null,
        },
        is_org_admin: false,
        connected_server_ids: [],
        revoked_server_ids: [],
    }
}

describe('gatewayMemberLogic', () => {
    let parentLogic: ReturnType<typeof mcpGatewayLogic.build>
    let logic: ReturnType<typeof gatewayMemberLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockConfigList.mockResolvedValue({
            is_admin: true,
            allow_custom_servers: true,
            allow_member_agent_access: true,
        })
        mockMembersList.mockResolvedValue({ count: 0, results: [] })
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })

        parentLogic = mcpGatewayLogic()
        parentLogic.mount()
        await expectLogic(parentLogic).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
        parentLogic.unmount()
    })

    it('loads the member directly while reusing the gateway server registry', async () => {
        const member = gatewayMember()
        const pendingMember = deferred<GatewayMemberSummaryApi>()
        mockMemberRetrieve.mockReturnValue(pendingMember.promise)

        logic = gatewayMemberLogic({ id: String(member.user.id) })
        logic.mount()

        expect(logic.values.member).toBeNull()
        expect(logic.values.memberInitialized).toBe(false)
        expect(logic.values.memberLoading).toBe(true)

        pendingMember.resolve(member)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockMemberRetrieve).toHaveBeenCalledWith(expect.any(String), String(member.user.id))
        expect(mockServersList).toHaveBeenCalledTimes(1)
        expect(logic.values.member).toEqual(member)
        expect(logic.values.memberInitialized).toBe(true)
    })
})
