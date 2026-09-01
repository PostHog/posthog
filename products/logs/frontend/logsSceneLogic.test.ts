import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator } from '~/types'

import {
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
    facetSelection,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'

import { logsSceneLogic } from './logsSceneLogic'

describe('logsSceneLogic', () => {
    let logic: ReturnType<typeof logsSceneLogic.build>

    // The two legacy params fold into filterGroup, which is where the selection lives.
    const selectedLevels = (): string[] =>
        facetSelection(logic.values.filters.filterGroup, SEVERITY_LEVEL_FILTER).included
    const selectedServices = (): string[] =>
        facetSelection(logic.values.filters.filterGroup, SERVICE_NAME_FILTER).included

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

            expect(selectedLevels()).toEqual(expected)
        })

        it.each([
            ['JSON string array', '["my-service","other-service"]', ['my-service', 'other-service']],
            ['single item JSON array', '["api"]', ['api']],
        ])('parses serviceNames from %s', async (_, urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { serviceNames: urlValue })
            }).toFinishAllListeners()

            expect(selectedServices()).toEqual(expected)
        })

        it.each<[string, string]>([
            ['severityLevels', '["error"]'],
            ['serviceNames', '["api"]'],
        ])('drops the %s param once it has been applied', async (param, urlValue) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { [param]: urlValue })
            }).toFinishAllListeners()

            // Left in place, the param is read again on every later URL change and folds its
            // selection back in, contradicting whatever the rail did to it since.
            expect(router.values.searchParams[param]).toBeUndefined()
            expect(router.values.searchParams.filterGroup).not.toBeUndefined()
        })

        it.each<[string, string, string[], string[]]>([
            [
                'a group that already selects the facet wins over the param',
                '["error"]',
                ['error', 'warn'],
                ['error', 'warn'],
            ],
            ['a group silent about the facet lets the param through', '["error"]', [], ['error']],
        ])('%s', async (_, param, groupLevels, expected) => {
            const values = groupLevels.length
                ? [{ key: 'severity_level', type: 'log', operator: 'exact', value: groupLevels }]
                : []
            await expectLogic(logic, () => {
                router.actions.push('/logs', {
                    severityLevels: param,
                    filterGroup: JSON.stringify({
                        type: FilterLogicalOperator.And,
                        values: [{ type: FilterLogicalOperator.And, values }],
                    }),
                })
            }).toFinishAllListeners()

            expect(selectedLevels()).toEqual(expected)
        })

        it('filters out malformed JSON as invalid severity level', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: 'not-valid-json[' })
            }).toFinishAllListeners()

            // parseTagsFilter falls back to comma-separated parsing, then validation filters invalid levels
            expect(selectedLevels()).toEqual([])
        })

        it('filters out non-array JSON as invalid severity level', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: '"just-a-string"' })
            }).toFinishAllListeners()

            // parseTagsFilter falls back to comma-separated parsing, then validation filters invalid levels
            expect(selectedLevels()).toEqual([])
        })

        it('handles comma-separated values via parseTagsFilter', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: 'error,warn,info' })
            }).toFinishAllListeners()

            expect(selectedLevels()).toEqual(['error', 'warn', 'info'])
        })

        it.each([
            ['a valid lens', 'patterns', 'patterns'],
            ['an unrecognised lens falls back to the default', 'nonsense', 'logs'],
        ])('applies viewMode from the URL: %s', async (_, urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { viewMode: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.viewMode).toEqual(expected)
        })

        it('syncs lens switches back to the URL, dropping the param for the default lens', async () => {
            // The round-trip contract for shareable lens links: switching to Patterns writes
            // ?viewMode=patterns, and returning to Logs (the default) removes the param
            // instead of pinning viewMode=logs into every copied URL.
            await expectLogic(logic, () => {
                logic.actions.setViewMode('patterns')
            }).toFinishAllListeners()
            expect(router.values.searchParams.viewMode).toEqual('patterns')

            await expectLogic(logic, () => {
                logic.actions.setViewMode('logs')
            }).toFinishAllListeners()
            expect(router.values.searchParams.viewMode).toBeUndefined()
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

            expect(selectedLevels()).toEqual(expected)
        })

        it('parses a stringified filterGroup from the URL (e.g. a cross-product session link)', async () => {
            const filterGroup = {
                type: 'AND',
                values: [{ type: 'OR', values: [{ key: 'posthogSessionId', value: ['sess-1'], operator: 'exact' }] }],
            }
            await expectLogic(logic, () => {
                router.actions.push('/logs', { filterGroup: JSON.stringify(filterGroup) })
            }).toFinishAllListeners()

            expect(logic.values.filters.filterGroup).toEqual(filterGroup)
        })

        it('ignores a malformed filterGroup in the URL', async () => {
            const before = logic.values.filters.filterGroup
            await expectLogic(logic, () => {
                router.actions.push('/logs', { filterGroup: '{not valid json' })
            }).toFinishAllListeners()

            expect(logic.values.filters.filterGroup).toEqual(before)
        })
    })

    describe('activeTab URL sync', () => {
        it('defaults to viewer', () => {
            expect(logic.values.activeTab).toEqual('viewer')
        })

        it.each([
            ['viewer', 'viewer'],
            ['anomalies', 'anomalies'],
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

    describe('anomalies URL sync', () => {
        const anomaliesRange = { date_from: '-1wStart', date_to: 'wStart' }

        it('writes the picked service and week to the URL, and drops each at its default', async () => {
            await expectLogic(logic, () => {
                logic.actions.setServiceName('checkout')
                logic.actions.setDateRange(anomaliesRange)
            }).toFinishAllListeners()

            expect(router.values.searchParams.serviceName).toEqual('checkout')
            expect(router.values.searchParams.anomaliesDateRange).toEqual(anomaliesRange)

            await expectLogic(logic, () => {
                logic.actions.setServiceName(null)
                logic.actions.setDateRange({ date_from: '-7d' })
            }).toFinishAllListeners()

            expect(router.values.searchParams.serviceName).toBeUndefined()
            expect(router.values.searchParams.anomaliesDateRange).toBeUndefined()
        })

        it('restores both from a shared URL', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', {
                    activeTab: 'anomalies',
                    serviceName: 'checkout',
                    anomaliesDateRange: JSON.stringify(anomaliesRange),
                })
            }).toFinishAllListeners()

            expect(logic.values.serviceName).toEqual('checkout')
            expect(logic.values.dateRange).toEqual(anomaliesRange)
        })

        it('leaves the log viewer window alone', async () => {
            // The two ranges share one URL, so writing the anomalies week must not move the
            // viewer's own dateRange param and silently reframe the user's logs.
            const viewerRange = logic.values.filters.dateRange

            await expectLogic(logic, () => {
                logic.actions.setDateRange(anomaliesRange)
            }).toFinishAllListeners()

            expect(router.values.searchParams.dateRange).not.toEqual(anomaliesRange)
            expect(logic.values.filters.dateRange).toEqual(viewerRange)
        })

        it('returns to the default week when the param drops out of the URL', async () => {
            // The default week writes no param, so navigating back past a week that did write
            // one has to clear it. Without this the picker keeps the older week on the way back.
            await expectLogic(logic, () => {
                router.actions.push('/logs', {
                    activeTab: 'anomalies',
                    anomaliesDateRange: JSON.stringify(anomaliesRange),
                })
            }).toFinishAllListeners()
            expect(logic.values.dateRange).toEqual(anomaliesRange)

            // The write arms the URL sync guard and clears it in a macrotask, which
            // toFinishAllListeners does not flush. A real back-navigation lands well after that.
            await new Promise((resolve) => setTimeout(resolve, 0))

            await expectLogic(logic, () => {
                router.actions.push('/logs', { activeTab: 'anomalies' })
            }).toFinishAllListeners()

            expect(logic.values.dateRange).toEqual({ date_from: '-7d' })
        })

        it('ignores the anomalies params while another tab is active', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', {
                    activeTab: 'viewer',
                    serviceName: 'checkout',
                    anomaliesDateRange: JSON.stringify(anomaliesRange),
                })
            }).toFinishAllListeners()

            expect(logic.values.serviceName).toBeNull()
            expect(logic.values.dateRange).toEqual({ date_from: '-7d' })
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
