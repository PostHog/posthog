import { router } from 'kea-router'

import api from 'lib/api'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointSceneLogic, EndpointTab, extractBreakdownPropertyNames } from './endpointSceneLogic'
import { endpointsMaterializationSuggestionCreate } from './generated/api'

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
            listVersions: jest.fn().mockResolvedValue({ results: [] }),
        },
    },
    ApiConfig: {
        getCurrentTeamId: jest.fn(() => 1),
    },
}))

const mockEditorLogic = {
    values: { queryInput: 'SELECT 1' },
    actions: {
        setQueryInput: jest.fn(),
        setSourceQuery: jest.fn(),
        setSuggestedQueryInput: jest.fn(),
    },
}

jest.mock('scenes/data-warehouse/editor/sqlEditorLogic', () => ({
    sqlEditorLogic: Object.assign(
        jest.fn(() => ({ mount: jest.fn(() => jest.fn()) })),
        { findMounted: jest.fn(() => mockEditorLogic) }
    ),
}))

jest.mock('./generated/api', () => ({
    endpointsMaterializationSuggestionCreate: jest.fn(),
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
    getTabsSnapshotForHistory: (tabs: any[]) => tabs.map(({ sceneParams: _omit, ...rest }) => ({ ...rest })),
}))

describe('endpointSceneLogic', () => {
    let logic: ReturnType<typeof endpointSceneLogic.build>

    const endpoint = {
        id: 'endpoint-id',
        name: 'test-endpoint',
        current_version: 1,
        query: null,
        is_materialized: false,
        data_freshness_seconds: 86400,
        materialization: null,
        description: 'Current endpoint',
    } as any

    beforeEach(async () => {
        jest.clearAllMocks()
        // The bare jest.fn() in the module mock resolves undefined, which the endpoint
        // loader would feed straight into its reducer. Echo the requested version so the
        // URL's version param survives the mount-time viewingVersion sync.
        ;(api.endpoint.get as jest.Mock).mockImplementation((_name: string, version?: number) =>
            Promise.resolve(version === undefined ? endpoint : { ...endpoint, version })
        )
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
        // Let the mount-time load settle with the default mock, so per-test overrides
        // apply cleanly to the fetches each test triggers
        await expectLogic(logic).toFinishAllListeners()
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

    describe('extractBreakdownPropertyNames', () => {
        // Must match the backend's iter_breakdowns, which stringifies every entry (str(name)),
        // so numeric legacy breakdowns (e.g. cohort IDs) land in the OpenAPI required set as strings
        test.each([
            ['legacy string', { breakdown: '$browser', breakdown_type: 'event' }, ['$browser']],
            ['legacy numeric cohort', { breakdown: 2, breakdown_type: 'cohort' }, ['2']],
            ['legacy numeric list', { breakdown: [2, 5], breakdown_type: 'cohort' }, ['2', '5']],
            ['breakdowns form', { breakdowns: [{ property: '$browser' }, { property: 7 }] }, ['$browser', '7']],
        ])('%s', (_name, breakdownFilter, expected) => {
            expect(extractBreakdownPropertyNames({ kind: 'TrendsQuery', breakdownFilter })).toEqual(expected)
        })
    })

    describe('optionalBreakdownProperties reducer', () => {
        it('seeds from the loaded endpoint', async () => {
            const endpointWithOptional = { ...endpoint, optional_breakdown_properties: ['$browser'] }
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess(endpointWithOptional)
            }).toFinishAllListeners()

            expect(logic.values.optionalBreakdownProperties).toEqual(['$browser'])
        })

        it('toggleBreakdownOptional flips a single property both ways', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleBreakdownOptional('$browser')
            }).toMatchValues({ optionalBreakdownProperties: ['$browser'] })

            await expectLogic(logic, () => {
                logic.actions.toggleBreakdownOptional('$browser')
            }).toMatchValues({ optionalBreakdownProperties: [] })
        })

        it('toggleBreakdownOptional preserves order across independent properties', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleBreakdownOptional('$browser')
                logic.actions.toggleBreakdownOptional('$os')
            }).toMatchValues({ optionalBreakdownProperties: ['$browser', '$os'] })

            await expectLogic(logic, () => {
                logic.actions.toggleBreakdownOptional('$browser')
            }).toMatchValues({ optionalBreakdownProperties: ['$os'] })
        })

        it('resetOptionalBreakdownProperties wins on version switch', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleBreakdownOptional('$browser')
            }).toMatchValues({ optionalBreakdownProperties: ['$browser'] })

            const versionData = {
                ...endpoint,
                version: 2,
                optional_breakdown_properties: ['$os'],
            }
            await expectLogic(logic, () => {
                logic.actions.setViewingVersion(versionData)
            }).toFinishAllListeners()

            expect(logic.values.optionalBreakdownProperties).toEqual(['$os'])
        })
    })

    describe('materialization suggestion', () => {
        const hogqlEndpoint = {
            ...endpoint,
            query: { kind: 'HogQLQuery', query: 'SELECT count() FROM events WHERE 1 = 1 OR 0 = 1' },
        }
        const suggestion = {
            suggestion_status: 'ok',
            suggested_query: 'SELECT count() FROM events',
            explanation: 'Dropped the redundant OR branch.',
            attempts: 1,
            error: null,
            original_reason: 'Variables in OR conditions are not supported for materialization',
        }

        it('applies the suggestion to the latest-version editor even when the cached editor tab is stale', async () => {
            logic.actions.loadEndpointSuccess(hogqlEndpoint)
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadMaterializationSuggestionSuccess(suggestion as any)

            logic.cache.sqlEditorTabId = 'endpoint-query-2'
            logic.actions.applyMaterializationSuggestion()

            expect((sqlEditorLogic as any).findMounted).toHaveBeenCalledWith(
                expect.objectContaining({ tabId: 'endpoint-query-latest' })
            )
            expect(mockEditorLogic.actions.setSuggestedQueryInput).toHaveBeenCalledWith(
                suggestion.suggested_query,
                'materialization_fix'
            )
        })

        it('does nothing without a validated suggestion', async () => {
            logic.actions.loadEndpointSuccess(hogqlEndpoint)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.applyMaterializationSuggestion()

            expect((sqlEditorLogic as any).findMounted).not.toHaveBeenCalled()
            expect(mockEditorLogic.actions.setSuggestedQueryInput).not.toHaveBeenCalled()
        })

        it('reuses the cached suggestion on reopen and only re-requests on regenerate', async () => {
            ;(endpointsMaterializationSuggestionCreate as jest.Mock).mockResolvedValue(suggestion)
            logic.actions.loadEndpointSuccess(hogqlEndpoint)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.openMaterializationSuggestionModal()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.closeMaterializationSuggestionModal()
            logic.actions.openMaterializationSuggestionModal()
            await expectLogic(logic).toFinishAllListeners()
            expect(endpointsMaterializationSuggestionCreate).toHaveBeenCalledTimes(1)

            logic.actions.regenerateMaterializationSuggestion()
            await expectLogic(logic).toFinishAllListeners()
            expect(endpointsMaterializationSuggestionCreate).toHaveBeenCalledTimes(2)
        })
    })
})
