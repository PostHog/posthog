import { router } from 'kea-router'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointSceneLogic, EndpointTab } from './endpointSceneLogic'

const mockSceneLogic = {
    isMounted: jest.fn(() => true),
    findMounted: jest.fn(),
    values: {
        activeTabId: 'active-tab',
        tabs: [] as any[],
    },
    actions: {
        setTabs: jest.fn((tabs) => {
            mockSceneLogic.values.tabs = tabs
        }),
    },
}

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        endpoint: {
            get: jest.fn(),
            run: jest.fn(),
        },
    },
}))

jest.mock('./endpointsLogic', () => ({
    endpointsLogic: {
        loadEndpoints: jest.fn(() => ({ type: 'load endpoints (mock)' })),
    },
}))

jest.mock('~/layout/scenes/sceneLayoutLogic', () => ({
    sceneLayoutLogic: {
        setScenePanelOpen: jest.fn((open?: boolean) => ({ type: 'set scene panel open (mock)', open })),
    },
}))

jest.mock('scenes/teamLogic', () => ({
    teamLogic: {
        addProductIntent: jest.fn((properties?: Record<string, any>) => ({
            type: 'add product intent (mock)',
            properties,
        })),
    },
}))

jest.mock('scenes/sceneLogic', () => ({
    get sceneLogic() {
        return mockSceneLogic
    },
}))

describe('endpointSceneLogic', () => {
    let logic: ReturnType<typeof endpointSceneLogic.build>

    const endpoint = {
        id: 'endpoint-id',
        name: 'test-endpoint',
        current_version: 1,
        query: null,
        is_materialized: false,
        cache_age_seconds: null,
        materialization: null,
        description: 'Current endpoint',
    } as any

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests(false)
        localStorage.clear()
        sessionStorage.clear()

        router.actions.push('/insights')

        mockSceneLogic.findMounted.mockReturnValue(mockSceneLogic)
        mockSceneLogic.values.activeTabId = 'active-tab'
        mockSceneLogic.values.tabs = [
            {
                id: 'active-tab',
                active: true,
                pathname: '/insights',
                search: '',
                hash: '',
                title: 'Insights',
                iconType: 'insight',
                pinned: false,
                sceneParams: { params: {}, searchParams: {}, hashParams: {} },
            },
            {
                id: 'endpoint-tab',
                active: false,
                pathname: '/endpoints/test-endpoint',
                search: '?tab=query&version=2',
                hash: '',
                title: 'Test endpoint',
                iconType: 'endpoints',
                pinned: false,
                sceneParams: {
                    params: { name: 'test-endpoint' },
                    searchParams: { tab: EndpointTab.QUERY, version: '2' },
                    hashParams: {},
                },
            },
        ]

        logic = endpointSceneLogic({ tabId: 'endpoint-tab' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the requested version from the inactive tab state', async () => {
        const versionData = { ...endpoint, version: 2, description: 'Version 2' }
        ;(api.endpoint.get as jest.Mock).mockResolvedValue(versionData)

        const initialPathname = router.values.location.pathname

        logic.actions.loadEndpointSuccess(endpoint)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            viewingVersion: versionData,
        })

        expect(api.endpoint.get).toHaveBeenCalledWith('test-endpoint', 2)
        expect(router.values.location.pathname).toEqual(initialPathname)
    })

    it('keeps URL updates scoped to the inactive tab when viewingVersion changes', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadEndpointSuccess(endpoint)
        }).toMatchValues({
            endpoint,
        })

        const versionData = { ...endpoint, version: 2, description: 'Version 2' }
        const initialPathname = router.values.location.pathname

        await expectLogic(logic, () => {
            logic.actions.setViewingVersion(versionData)
        }).toMatchValues({
            viewingVersion: versionData,
        })

        const endpointTab = mockSceneLogic.values.tabs.find((tab) => tab.id === 'endpoint-tab')

        expect(router.values.location.pathname).toEqual(initialPathname)
        expect(endpointTab?.pathname).toEqual('/endpoints/test-endpoint')
        expect(endpointTab?.sceneParams?.searchParams).toMatchObject({
            tab: EndpointTab.QUERY,
            version: 2,
        })
    })
})
