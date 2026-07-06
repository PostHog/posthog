import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { logsSceneLogic } from './logsSceneLogic'

describe('logsSceneLogic', () => {
    let logic: ReturnType<typeof logsSceneLogic.build>

    beforeEach(async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/logs/query/': () => [200, { results: [], maxExportableLogs: 5000 }],
                '/api/environments/:team_id/logs/sparkline/': () => [200, []],
            },
        })
        initKeaTests()
        logic = logsSceneLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('URL parameter parsing', () => {
        it.each([
            ['JSON string array', '["error","warn"]', ['error', 'warn']],
            ['single item JSON array', '["info"]', ['info']],
            ['empty JSON array', '[]', []],
        ])('parses severityLevels from %s', async (_, urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.filters.severityLevels).toEqual(expected)
        })

        it.each([
            ['JSON string array', '["my-service","other-service"]', ['my-service', 'other-service']],
            ['single item JSON array', '["api"]', ['api']],
        ])('parses serviceNames from %s', async (_, urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { serviceNames: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.filters.serviceNames).toEqual(expected)
        })

        it('filters out malformed JSON as invalid severity level', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: 'not-valid-json[' })
            }).toFinishAllListeners()

            // parseTagsFilter falls back to comma-separated parsing, then validation filters invalid levels
            expect(logic.values.filters.severityLevels).toEqual([])
        })

        it('filters out non-array JSON as invalid severity level', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: '"just-a-string"' })
            }).toFinishAllListeners()

            // parseTagsFilter falls back to comma-separated parsing, then validation filters invalid levels
            expect(logic.values.filters.severityLevels).toEqual([])
        })

        it('handles comma-separated values via parseTagsFilter', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: 'error,warn,info' })
            }).toFinishAllListeners()

            expect(logic.values.filters.severityLevels).toEqual(['error', 'warn', 'info'])
        })

        it.each([
            ['completely invalid value', '["invalid-level"]', []],
            ['typo in valid level', '["debug123"]', []],
            ['mix of valid and invalid', '["error","not-a-level","warn"]', ['error', 'warn']],
            ['invalid comma-separated', 'invalid,also-invalid', []],
        ])('filters out invalid severity levels (%s)', async (_, urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.filters.severityLevels).toEqual(expected)
        })
    })

    describe('activeTab URL sync', () => {
        it('defaults to viewer', () => {
            expect(logic.values.activeTab).toEqual('viewer')
        })

        it.each([
            ['viewer', 'viewer'],
            ['configuration', 'configuration'],
        ])('parses valid activeTab "%s" from URL', async (urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { activeTab: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.activeTab).toEqual(expected)
        })

        it.each([
            ['unknown string', 'invalid'],
            ['array', ['viewer']],
            ['object', { key: 'viewer' }],
            ['number', 42],
        ])('ignores invalid activeTab (%s)', async (_, urlValue) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { activeTab: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.activeTab).toEqual('viewer')
        })

        it('syncs activeTab to URL on setActiveTab', async () => {
            await expectLogic(logic, () => {
                logic.actions.setActiveTab('configuration')
            }).toFinishAllListeners()

            expect(logic.values.activeTab).toEqual('configuration')
            expect(router.values.searchParams).toHaveProperty('activeTab', 'configuration')
        })

        it('removes activeTab from URL when set to default', async () => {
            // First set to non-default
            await expectLogic(logic, () => {
                logic.actions.setActiveTab('configuration')
            }).toFinishAllListeners()

            // Then set back to default
            await expectLogic(logic, () => {
                logic.actions.setActiveTab('viewer')
            }).toFinishAllListeners()

            expect(logic.values.activeTab).toEqual('viewer')
            expect(router.values.searchParams).not.toHaveProperty('activeTab')
        })
    })

    describe('facetNameSearch URL sync', () => {
        it('parses facetNameSearch from URL', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { facetNameSearch: 'namespace' })
            }).toFinishAllListeners()

            expect(logic.values.facetNameSearch).toEqual('namespace')
        })

        it('syncs facetNameSearch to URL on setFacetNameSearch', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFacetNameSearch('kube')
            }).toFinishAllListeners()

            expect(logic.values.facetNameSearch).toEqual('kube')
            expect(router.values.searchParams).toHaveProperty('facetNameSearch', 'kube')
        })

        it('removes facetNameSearch from URL when cleared', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFacetNameSearch('kube')
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setFacetNameSearch('')
            }).toFinishAllListeners()

            expect(logic.values.facetNameSearch).toEqual('')
            expect(router.values.searchParams).not.toHaveProperty('facetNameSearch')
        })
    })
})
