import { router } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointSceneLogic, EndpointTab } from './endpointSceneLogic'

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

    describe('playground typed form', () => {
        beforeEach(() => {
            // The outer beforeEach parks the URL on `version=2`, which makes
            // loadEndpointSuccess run its version-loading path and bleed
            // setPlaygroundVersion(2) into these tests. Drop the version param and reset
            // the api mock so playground specs start from a clean state.
            ;(api.endpoint.get as jest.Mock).mockReset()
            ;(api.endpoint.get as jest.Mock).mockResolvedValue(undefined)
            router.actions.push(urls.endpoint('test-endpoint'), { tab: EndpointTab.QUERY })
        })

        const trendsEndpoint: any = {
            ...endpoint,
            query: {
                kind: 'TrendsQuery',
                series: [{ kind: 'EventsNode' }],
                breakdownFilter: {
                    breakdowns: [
                        { property: '$os', type: 'event' },
                        { property: '$browser', type: 'event' },
                    ],
                },
            },
            is_materialized: true,
        }

        const inlineHogQLEndpoint: any = {
            ...endpoint,
            query: {
                kind: 'HogQLQuery',
                query: 'SELECT count() FROM events WHERE event = {variables.event_name}',
                variables: {
                    'var-evt-1': {
                        variableId: 'var-evt-1',
                        code_name: 'event_name',
                        value: '$pageview',
                    },
                },
            },
            is_materialized: false,
        }

        it('derives required breakdown specs and seeds Send=on for each', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess(trendsEndpoint)
            }).toFinishAllListeners()

            const specs = logic.values.playgroundVariableSpecs
            expect(specs.map((s: any) => s.name)).toEqual(['$os', '$browser'])
            specs.forEach((s: any) => {
                expect(s.required).toBe(true)
                expect(s.sendLocked).toBe(true)
            })
            expect(logic.values.playgroundVariableSent).toEqual({ $os: true, $browser: true })
        })

        it('respects optional_breakdown_properties: optional vars default to Send=off and unlocked', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess({
                    ...trendsEndpoint,
                    optional_breakdown_properties: ['$browser'],
                })
            }).toFinishAllListeners()

            const specs = logic.values.playgroundVariableSpecs
            const browser = specs.find((s: any) => s.name === '$browser')
            const os = specs.find((s: any) => s.name === '$os')
            expect(browser).toMatchObject({ required: false, sendLocked: false, defaultSent: false })
            expect(os).toMatchObject({ required: true, sendLocked: true, defaultSent: true })
            expect(logic.values.playgroundVariableSent).toEqual({ $os: true, $browser: false })
        })

        it('inline HogQL var with a default seeds Send=off (runtime substitutes the default)', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess(inlineHogQLEndpoint)
            }).toFinishAllListeners()

            const specs = logic.values.playgroundVariableSpecs
            expect(specs).toHaveLength(1)
            expect(specs[0]).toMatchObject({
                name: 'event_name',
                required: false,
                sendLocked: false,
                defaultSent: false,
                defaultValue: '$pageview',
            })
        })

        it('materialized HogQL var is required and locked', async () => {
            const matHogQL = { ...inlineHogQLEndpoint, is_materialized: true }
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess(matHogQL)
            }).toFinishAllListeners()

            expect(logic.values.playgroundVariableSpecs[0]).toMatchObject({
                required: true,
                sendLocked: true,
                defaultSent: true,
            })
        })

        it('playgroundPayload drops sent=false variables entirely', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess({
                    ...trendsEndpoint,
                    optional_breakdown_properties: ['$browser'],
                })
                logic.actions.setPlaygroundVariableValue('$os', 'Mac OS X')
                logic.actions.setPlaygroundVariableValue('$browser', 'Chrome')
            }).toFinishAllListeners()

            // $browser is sent=false (it's optional, default off). Even with a value typed in,
            // it shouldn't appear in the payload.
            expect(logic.values.playgroundPayload).toEqual({
                variables: { $os: 'Mac OS X' },
            })

            // Flip Send on for $browser — it now joins the payload.
            await expectLogic(logic, () => {
                logic.actions.setPlaygroundVariableSent('$browser', true)
            }).toFinishAllListeners()
            expect(logic.values.playgroundPayload.variables).toEqual({
                $os: 'Mac OS X',
                $browser: 'Chrome',
            })
        })

        it('playgroundPayload only emits non-default request options', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess(trendsEndpoint)
                logic.actions.setPlaygroundVariableValue('$os', 'Mac OS X')
                logic.actions.setPlaygroundVariableValue('$browser', 'Chrome')
            }).toFinishAllListeners()

            // Default refresh=cache, no limit, no version → no extra fields in the payload.
            expect(Object.keys(logic.values.playgroundPayload).sort()).toEqual(['variables'])

            await expectLogic(logic, () => {
                logic.actions.setPlaygroundRefresh('force')
                logic.actions.setPlaygroundLimit(50)
                logic.actions.setPlaygroundVersion(2)
            }).toFinishAllListeners()

            expect(logic.values.playgroundPayload).toMatchObject({
                refresh: 'force',
                limit: 50,
                version: 2,
            })
        })

        it('JSON preview reflects the live payload as the form changes', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess(trendsEndpoint)
                logic.actions.setPlaygroundVariableValue('$os', 'Linux')
                logic.actions.setPlaygroundVariableValue('$browser', 'Firefox')
            }).toFinishAllListeners()

            const parsed = JSON.parse(logic.values.playgroundPayloadJsonPreview)
            expect(parsed).toEqual({ variables: { $os: 'Linux', $browser: 'Firefox' } })
        })

        it('debug switch shows up as debug:true in the payload', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess(trendsEndpoint)
                logic.actions.setPlaygroundVariableValue('$os', 'Mac OS X')
                logic.actions.setPlaygroundVariableValue('$browser', 'Chrome')
                logic.actions.setDebugMode(true)
            }).toFinishAllListeners()

            expect(logic.values.playgroundPayload).toMatchObject({ debug: true })
        })

        it('re-seeds the form when switching versions', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEndpointSuccess(trendsEndpoint)
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.setPlaygroundVariableValue('$os', 'Mac OS X')
            }).toMatchValues({ playgroundVariableValues: expect.objectContaining({ $os: 'Mac OS X' }) })

            // Switch to a viewing-version that has a different breakdown set entirely.
            const versionWithDifferentBreakdowns = {
                ...trendsEndpoint,
                version: 2,
                query: {
                    ...trendsEndpoint.query,
                    breakdownFilter: { breakdowns: [{ property: '$country', type: 'event' }] },
                },
            }
            await expectLogic(logic, () => {
                logic.actions.setViewingVersion(versionWithDifferentBreakdowns)
            }).toFinishAllListeners()

            expect(logic.values.playgroundVariableSpecs.map((s: any) => s.name)).toEqual(['$country'])
            // Old values for vars that no longer exist are dropped from the seeded map.
            expect(logic.values.playgroundVariableValues).toEqual({ $country: '' })
        })
    })
})
