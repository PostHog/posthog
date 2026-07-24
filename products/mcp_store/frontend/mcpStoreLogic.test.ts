import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mcpStoreLogic } from './mcpStoreLogic'

describe('mcpStoreLogic', () => {
    let logic: ReturnType<typeof mcpStoreLogic.build>

    // An empty 200 body (no JSON) makes api.get() resolve to null. The list loaders
    // must degrade that to [] rather than dereference null.results and crash the panel.
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/mcp_servers': () => [200],
                '/api/environments/:team_id/mcp_server_installations': () => [200],
            },
        })
        initKeaTests()
        logic = mcpStoreLogic()
        logic.mount()
    })

    it('degrades an empty API body to empty lists instead of crashing', async () => {
        await expectLogic(logic).toDispatchActions(['loadServersSuccess', 'loadInstallationsSuccess']).toMatchValues({
            servers: [],
            installations: [],
        })
    })
})
