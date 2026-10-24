import { router } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointSceneLogic, EndpointTab, extractBreakdownPropertyNames } from './endpointSceneLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    ApiConfig: { getCurrentTeamId: () => 1 },
    default: {
        endpoint: {
            get: jest.fn(),
            run: jest.fn(),
            listVersions: jest.fn().mockResolvedValue({ results: [] }),
        },
    },
}))

jest.mock('./generated/api', () => ({
    endpointsRetrieve: (_projectId: number, name: string) => jest.requireMock('lib/api').default.endpoint.get(name),
}))

jest.mock('scenes/data-warehouse/editor/sqlEditorLogic', () => ({
    sqlEditorLogic: jest.fn(() => ({ mount: jest.fn(() => jest.fn()) })),
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

    it('keeps an explicit current version pinned in the URL', async () => {
        router.actions.push(urls.endpoint(endpoint.name), { tab: EndpointTab.LINEAGE, version: 1 })
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toMatchObject({ version: 1, tab: EndpointTab.LINEAGE })
        expect(logic.values.viewingVersion).toMatchObject({ version: 1 })

        logic.actions.setViewingVersion(null)
        expect(router.values.searchParams).toEqual({ tab: EndpointTab.LINEAGE })
    })

    it('keeps visited model panels available when switching tabs', async () => {
        router.actions.push(urls.endpoint(endpoint.name), { tab: EndpointTab.DATA_QUALITY })
        router.actions.push(urls.endpoint(endpoint.name), { tab: EndpointTab.LINEAGE })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.visitedTabs).toEqual([EndpointTab.QUERY, EndpointTab.DATA_QUALITY, EndpointTab.LINEAGE])
        expect(logic.values.activeTab).toEqual(EndpointTab.LINEAGE)
    })

    it('uses the query tab when the URL names an unknown tab', async () => {
        router.actions.push(urls.endpoint(endpoint.name), { tab: 'missing-tab' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeTab).toEqual(EndpointTab.QUERY)
    })

    test.each([EndpointTab.LINEAGE, EndpointTab.DATA_QUALITY])(
        'returns to the current version when a requested version is missing on %s',
        async (tab) => {
            ;(api.endpoint.get as jest.Mock).mockRejectedValue(new Error('Version not found'))

            router.actions.push(urls.endpoint(endpoint.name), { tab, version: 99 })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.viewingVersion).toBeNull()
            expect(router.values.searchParams).toEqual({ tab })
        }
    )

    test.each(['success', 'failure'])(
        'ignores a late version %s after navigating to another endpoint',
        async (result) => {
            let complete!: (value: unknown) => void
            let fail!: (error: Error) => void
            const pendingVersion = new Promise((resolve, reject) => {
                complete = resolve
                fail = reject
            })
            const otherEndpoint = { ...endpoint, name: 'other-endpoint' }
            ;(api.endpoint.get as jest.Mock).mockImplementation((name: string, version?: number) =>
                name === endpoint.name
                    ? pendingVersion
                    : Promise.resolve(version === undefined ? otherEndpoint : { ...otherEndpoint, version })
            )

            router.actions.push(urls.endpoint(endpoint.name), { tab: EndpointTab.DATA_QUALITY, version: 3 })
            router.actions.push(urls.endpoint(otherEndpoint.name), { tab: EndpointTab.DATA_QUALITY, version: 3 })
            await expectLogic(logic).toFinishAllListeners()

            if (result === 'success') {
                complete({ ...endpoint, version: 3 })
            } else {
                fail(new Error('Version not found'))
            }
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.viewingVersion).toMatchObject({ name: otherEndpoint.name, version: 3 })
            expect(router.values.location.pathname).toContain(urls.endpoint(otherEndpoint.name))
        }
    )

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
})
