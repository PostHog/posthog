import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'
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
        // Mock the HTTP response so the request uses the generated client's URL builder.
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
        // The generated client converts an object to "[object Object]". The backend reads it as "last hour".
        expect(Array.from(requestParams?.values() ?? [])).not.toContain('[object Object]')
        // The endpoint uses its default window for a recent selection.
        expect(requestParams?.has('date_from')).toBe(false)
    })

    it('probes an older selection so its keys keep their facets', async () => {
        await mountAndLoad()

        logsViewerFiltersLogic({ id: ID }).actions.setFilters({ dateRange: { date_from: '-30d', date_to: null } })
        await expectLogic(logic).toDispatchActions(['loadPresentResourceKeys', 'loadPresentResourceKeysSuccess'])

        expect(requestParams?.get('date_from')).toEqual('-30d')
        expect(requestParams?.has('dateRange')).toBe(false)
    })

    it('shows the environment facet when only the env alias is emitted', async () => {
        emittedKeys = ['env']
        await mountAndLoad()

        const environment = logic.values.visibleFacets.find((f) => f.key === 'environment')
        expect(environment?.source).toMatchObject({ type: 'resourceAttribute', key: 'env' })
    })
})
