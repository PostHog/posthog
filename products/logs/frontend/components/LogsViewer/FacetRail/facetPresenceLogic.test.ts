import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { facetPresenceLogic } from './facetPresenceLogic'
import { FACETS, presenceProbeKeys } from './facets'

const ID = 'test-viewer'

describe('facetPresenceLogic', () => {
    let logic: ReturnType<typeof facetPresenceLogic.build>
    let requestParams: URLSearchParams | null
    let emittedKeys: string[]

    beforeEach(() => {
        requestParams = null
        emittedKeys = []
        // Mocked at the HTTP layer, not the generated client, so the request goes through the generated URL builder.
        useMocks({
            get: {
                '/api/projects/:team_id/logs/attributes/': ({ request }) => {
                    requestParams = new URL(request.url).searchParams
                    return [200, { results: emittedKeys.map((name) => ({ name })), count: emittedKeys.length }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mountAndLoad = async (): Promise<void> => {
        logic = facetPresenceLogic({ id: ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPresentResourceKeysSuccess'])
    }

    it('probes the curated keys without a date range the backend cannot parse', async () => {
        await mountAndLoad()

        expect(requestParams?.get('attribute_type')).toEqual('resource')
        expect(requestParams?.get('keys')?.split(',')).toEqual(presenceProbeKeys(FACETS))
        // An object param goes out as "[object Object]", which the backend reads as "last hour".
        expect(Array.from(requestParams?.values() ?? [])).not.toContain('[object Object]')
    })

    it('shows the environment facet when only the env alias is emitted', async () => {
        emittedKeys = ['env']
        await mountAndLoad()

        const environment = logic.values.visibleFacets.find((f) => f.key === 'environment')
        expect(environment?.source).toMatchObject({ type: 'resourceAttribute', key: 'env' })
    })
})
