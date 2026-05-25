import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

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
        logic = logsSceneLogic({ tabId: 'test-tab' })
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

    describe('URL-driven filter changes do not feed back into syncUrl', () => {
        const urlFilterGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            key: 'service.name',
                            value: ['api'],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.LogResourceAttribute,
                        },
                    ],
                },
            ],
        }

        it('applying filterGroup from URL does not redispatch syncUrl', async () => {
            // Drive a URL-driven filter change that mutates filterGroup (the only path that
            // fires the kea-subscriptions handler in logsViewerDataLogic). Without the
            // isApplyingUrlState guard, the subscription -> handleQueryChange listener would
            // re-emit syncUrl, exactly what the kea-router rapid URL change tracker flags.
            await expectLogic(logic, () => {
                router.actions.push('/logs', { filterGroup: urlFilterGroup })
            })
                .toDispatchActions(['handleQueryChange'])
                .toNotHaveDispatchedActions(['syncUrl'])

            expect(logic.values.filters.filterGroup).toEqual(urlFilterGroup)
        })

        it('subsequent user-triggered filter change still syncs to URL', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { filterGroup: urlFilterGroup })
            }).toFinishAllListeners()

            // A user-driven change after the URL apply must still write the URL via syncUrl.
            await expectLogic(logic, () => {
                logic.actions.setFilters({ severityLevels: ['warn'] })
            }).toDispatchActions(['handleQueryChange', 'syncUrl'])
        })
    })
})
