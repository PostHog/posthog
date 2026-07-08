import { router } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointSceneLogic, EndpointTab, extractBreakdownPropertyNames } from './endpointSceneLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        endpoint: {
            get: jest.fn(),
            run: jest.fn(),
            listVersions: jest.fn().mockResolvedValue({ results: [] }),
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
        initKeaTests(false)
        localStorage.clear()
        sessionStorage.clear()

        router.actions.push(urls.endpoint('test-endpoint'), { tab: EndpointTab.QUERY, version: '2' })

        logic = endpointSceneLogic()
        logic.mount()
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
