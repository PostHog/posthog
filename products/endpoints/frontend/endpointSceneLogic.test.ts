import { router } from 'kea-router'

import api from 'lib/api'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointSceneLogic, EndpointTab } from './endpointSceneLogic'
import { endpointsMaterializationSuggestionCreate } from './generated/api'

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
    sceneLogic: {
        isMounted: jest.fn(() => false),
        findMounted: jest.fn(() => null),
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

        router.actions.push(urls.endpoint('test-endpoint'), { tab: EndpointTab.QUERY, version: '2' })

        logic = endpointSceneLogic()
        logic.mount()
        // Let the mount-time load settle with the default mock, so per-test overrides
        // apply cleanly to the fetches each test triggers
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the requested version from the URL', async () => {
        const versionData = { ...endpoint, version: 2, description: 'Version 2' }
        ;(api.endpoint.get as jest.Mock).mockResolvedValue(versionData)

        logic.actions.loadEndpointSuccess(endpoint)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            viewingVersion: versionData,
        })

        expect(api.endpoint.get).toHaveBeenCalledWith('test-endpoint', 2)
        expect(router.values.location.pathname).toContain(urls.endpoint('test-endpoint'))
    })

    it('updates the URL version param when viewingVersion changes', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadEndpointSuccess(endpoint)
        }).toMatchValues({
            endpoint,
        })

        const versionData = { ...endpoint, version: 2, description: 'Version 2' }

        await expectLogic(logic, () => {
            logic.actions.setViewingVersion(versionData)
        }).toMatchValues({
            viewingVersion: versionData,
        })

        expect(router.values.location.pathname).toContain(urls.endpoint('test-endpoint'))
        expect(router.values.searchParams).toMatchObject({
            version: 2,
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
