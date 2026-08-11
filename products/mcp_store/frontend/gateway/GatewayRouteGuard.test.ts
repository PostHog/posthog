import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { mcpGatewayConfigList } from '../generated/api'
import { gatewayRouteGuardLogic } from './gatewayRouteGuardLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpGatewayConfigList: jest.fn(),
}))

const mockConfigList = jest.mocked(mcpGatewayConfigList)

describe('gatewayRouteGuardLogic', () => {
    let logic: ReturnType<typeof gatewayRouteGuardLogic.build> | null = null
    let unmountFeatureFlagLogic: (() => void) | null = null

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.resetAllMocks()
        unmountFeatureFlagLogic = featureFlagLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        logic = null
        unmountFeatureFlagLogic?.()
        unmountFeatureFlagLogic = null
    })

    function setGatewayEnabled(enabled: boolean): void {
        featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.MCP_GATEWAY] : [], {
            [FEATURE_FLAGS.MCP_GATEWAY]: enabled,
        })
    }

    async function mountGuard(requiresAdmin: boolean): Promise<void> {
        logic = gatewayRouteGuardLogic({ projectId: 997, requiresAdmin })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('sends users to the legacy Settings page after the gateway flag resolves off', async () => {
        router.actions.push(urls.mcpGatewayServer('server-id'))

        await mountGuard(false)

        expect(logic?.values.canRender).toBe(false)
        expect(router.values.location.pathname).toBe('/project/997/mcp-servers/server/server-id')

        setGatewayEnabled(false)
        await expectLogic(logic!).toFinishAllListeners()

        expect(router.values.location.pathname).toBe('/project/997/settings/mcp-servers')
        expect(mockConfigList).not.toHaveBeenCalled()
    })

    it('waits for a late gateway flag before deciding access', async () => {
        router.actions.push(urls.mcpGatewayServer('server-id'))

        await mountGuard(false)

        expect(logic?.values.canRender).toBe(false)
        expect(router.values.location.pathname).toBe('/project/997/mcp-servers/server/server-id')

        setGatewayEnabled(true)
        await expectLogic(logic!).toFinishAllListeners()

        expect(logic?.values.canRender).toBe(true)
        expect(router.values.location.pathname).toBe('/project/997/mcp-servers/server/server-id')
    })

    it('allows server details without an admin check when the gateway flag is on', async () => {
        setGatewayEnabled(true)
        router.actions.push(urls.mcpGatewayServer('server-id'))

        await mountGuard(false)

        expect(logic?.values.canRender).toBe(true)
        expect(router.values.location.pathname).toBe('/project/997/mcp-servers/server/server-id')
        expect(mockConfigList).not.toHaveBeenCalled()
    })

    it.each([
        [false, false, '/project/997/mcp-servers'],
        [true, true, '/project/997/mcp-servers/agent/agent-id'],
    ])(
        'enforces admin access for agent and member details when is_admin is %s',
        async (isAdmin, canRender, expectedPath) => {
            setGatewayEnabled(true)
            mockConfigList.mockResolvedValue({ is_admin: isAdmin, registered_template_ids: [] })
            router.actions.push(urls.mcpGatewayAgent('agent-id'))

            await mountGuard(true)

            expect(logic?.values.canRender).toBe(canRender)
            expect(router.values.location.pathname).toBe(expectedPath)
            expect(mockConfigList).toHaveBeenCalledWith('997')
        }
    )
})
