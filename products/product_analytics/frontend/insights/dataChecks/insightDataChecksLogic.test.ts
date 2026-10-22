import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import type { InsightVizNode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'
import type { InsightShortId } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { insightDataChecksLogic } from './insightDataChecksLogic'

const props = { dashboardItemId: '123' as InsightShortId }
const checksOf = (status: string): Record<string, unknown> => ({
    status,
    checks: [],
    coverage: null,
})

describe('insightDataChecksLogic', () => {
    let logic: ReturnType<typeof insightDataChecksLogic.build>
    let vizData: ReturnType<typeof insightVizDataLogic.build>
    const dataChecks = jest.fn()
    const cancelledQueryIds: string[] = []
    let sentSources: Record<string, unknown>[]
    let savedFilters: unknown[]
    let capture: jest.SpyInstance

    const loadedEvents = (): Record<string, unknown>[] =>
        capture.mock.calls
            .filter(([event]) => event === 'insight data checks loaded')
            .map(([, properties]) => properties as Record<string, unknown>)

    const answer =
        (response: [number, Record<string, unknown>], held?: Promise<void>, onSent?: () => void) =>
        async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
            const body = (await request.json()) as { query: { source: Record<string, unknown> } }
            sentSources.push(body.query.source)
            onSent?.()
            await held
            return response
        }

    const turnTheFlagOn = (): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INSIGHT_DATA_CHECKS], {
            [FEATURE_FLAGS.INSIGHT_DATA_CHECKS]: true,
        })
    }

    beforeEach(() => {
        dataChecks.mockReset()
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        sentSources = []
        savedFilters = []
        cancelledQueryIds.length = 0
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': { results: [] },
                '/api/projects/:team_id/insights/data_checks/': dataChecks,
            },
            patch: {
                '/api/projects/:team_id/': async ({ request }) => {
                    const body = (await request.json()) as { test_account_filters: unknown[] }
                    savedFilters.push(body.test_account_filters)
                    return [200, { ...teamLogic.values.currentTeam, ...body }]
                },
            },
            delete: {
                '/api/projects/:team_id/query/:id/': ({ params }) => {
                    cancelledQueryIds.push(params.id as string)
                    return [200, {}]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        insightDataLogic(props).mount()
        vizData = insightVizDataLogic(props)
        vizData.mount()
        logic = insightDataChecksLogic(props)
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('checks the insight when the flag arrives after the chart has loaded', async () => {
        dataChecks.mockImplementation(answer([200, checksOf('passed')]))
        await expectLogic(logic).toFinishAllListeners()
        expect(dataChecks).not.toHaveBeenCalled()

        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        expect(dataChecks).toHaveBeenCalledTimes(1)
        expect(logic.values.status).toBe('passed')
    })

    const holdTheFirstAnswer = (): { sent: Promise<void>; release: () => void } => {
        let markSent: () => void = () => {}
        let release: () => void = () => {}
        const sent = new Promise<void>((resolve) => {
            markSent = resolve
        })
        const held = new Promise<void>((resolve) => {
            release = resolve
        })
        dataChecks.mockImplementationOnce(answer([200, checksOf('passed')], held, markSent))
        dataChecks.mockImplementation(answer([200, checksOf('warning')]))
        return { sent, release: () => release() }
    }

    it('runs one check at a time, then checks the latest query', async () => {
        const first = holdTheFirstAnswer()
        turnTheFlagOn()
        await first.sent

        const firstQuery = logic.values.requestedQuery

        vizData.actions.updateQuerySource({ filterTestAccounts: true })
        logic.actions.checkData()
        vizData.actions.updateQuerySource({ dateRange: { date_from: '-30d' } })
        logic.actions.checkData()

        expect(logic.values.requestedQuery).toBe(firstQuery)
        expect(logic.values.status).toBe('checking')

        await expectLogic(logic, first.release).toFinishAllListeners()

        expect(sentSources).toEqual([
            expect.not.objectContaining({ filterTestAccounts: true }),
            expect.objectContaining({ filterTestAccounts: true, dateRange: { date_from: '-30d' } }),
        ])
        expect(logic.values.status).toBe('warning')
    })

    it('sends the whole query the chart runs, so the server reads the same events', async () => {
        dataChecks.mockImplementation(answer([200, checksOf('passed')]))
        const onChrome = { key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }
        const modifiers = { personsOnEventsMode: 'person_id_override_properties_joined' }
        const source = {
            kind: NodeKind.FunnelsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: 'signed up',
                    name: 'Sign up',
                    math: 'total',
                    properties: [onChrome],
                },
            ],
            dateRange: { date_from: '-30d' },
            filterTestAccounts: true,
            funnelsFilter: { funnelAggregateByHogQL: 'properties.$session_id', funnelVizType: 'steps' },
            breakdownFilter: { breakdown_type: 'event', breakdown: '$os' },
            modifiers,
        }
        insightDataLogic(props).actions.setQuery({
            kind: NodeKind.InsightVizNode,
            source,
        } as InsightVizNode)

        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        expect(sentSources.at(-1)).toEqual(source)
    })

    it('checks again after a refresh of the chart that ends during a check', async () => {
        const first = holdTheFirstAnswer()
        turnTheFlagOn()
        await first.sent
        vizData.actions.loadDataSuccess(
            {},
            { refresh: 'force_blocking', queryId: 'chart', pollOnly: false, overrideQuery: undefined }
        )

        await expectLogic(logic, first.release).toFinishAllListeners()

        expect(dataChecks).toHaveBeenCalledTimes(2)
    })

    it.each([
        ['again after a person refreshes the chart', 'force_blocking' as const, 2],
        ['once when the chart loads again for the same query', 'blocking' as const, 1],
    ])('checks %s', async (_name, refresh, requests) => {
        dataChecks.mockImplementation(answer([200, checksOf('passed')]))
        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        await expectLogic(logic, () => {
            vizData.actions.loadDataSuccess(
                {},
                { refresh, queryId: 'chart', pollOnly: false, overrideQuery: undefined }
            )
        }).toFinishAllListeners()

        expect(dataChecks).toHaveBeenCalledTimes(requests)
    })

    it.each([
        ['hides the mark from a person who may not run the checks', 403, 'unavailable'],
        ['reports a check the server could not finish', 500, 'failed'],
    ])('%s', async (_name, responseStatus, expected) => {
        dataChecks.mockImplementation(answer([responseStatus, { detail: 'No.' }]))

        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        expect(logic.values.status).toBe(expected)
    })

    it.each([
        ['problem', true],
        ['warning', true],
        ['passed', false],
    ])('keeps the label open after a %s result only when there is a finding', async (result, open) => {
        dataChecks.mockImplementation(answer([200, checksOf(result)]))
        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        logic.actions.closeLabel()

        expect(logic.values.labelOpen).toBe(open)
    })

    it('checks again when the chart type changes and the chart reuses its result', async () => {
        dataChecks.mockImplementation(answer([200, checksOf('passed')]))
        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        await expectLogic(logic, () => {
            vizData.actions.updateQuerySource({ trendsFilter: { display: ChartDisplayType.ActionsBar } })
        }).toFinishAllListeners()

        expect(dataChecks).toHaveBeenCalledTimes(2)
        expect(logic.values.status).toBe('passed')
    })

    it('does not check a chart with overrides, because only the server holds the query it runs', async () => {
        dataChecks.mockImplementation(answer([200, checksOf('passed')]))
        const overridden = { dashboardItemId: '456' as InsightShortId, filtersOverride: { date_from: '-1d' } }
        insightDataLogic(overridden).mount()
        insightVizDataLogic(overridden).mount()
        const overriddenLogic = insightDataChecksLogic(overridden)
        overriddenLogic.mount()

        await expectLogic(overriddenLogic, turnTheFlagOn).toFinishAllListeners()

        expect(overriddenLogic.values.status).toBe('unavailable')
        expect(dataChecks).toHaveBeenCalledTimes(1)
        overriddenLogic.unmount()
    })

    it('cancels a running check when the insight unmounts, so it frees the chart queue', async () => {
        let signal: AbortSignal | undefined
        let markSent: () => void = () => {}
        const sent = new Promise<void>((resolve) => {
            markSent = resolve
        })
        dataChecks.mockImplementation(async ({ request }: { request: Request }) => {
            signal = request.signal
            markSent()
            return await new Promise(() => {})
        })
        turnTheFlagOn()
        await sent

        logic.unmount()

        expect(signal?.aborted).toBe(true)
        logic.mount()
    })

    it('gives the chart queue back when the chart starts to load during a check, then checks again', async () => {
        let signal: AbortSignal | undefined
        let clientQueryId: string | undefined
        let markSent: () => void = () => {}
        const sent = new Promise<void>((resolve) => {
            markSent = resolve
        })
        dataChecks.mockImplementationOnce(async ({ request }: { request: Request }) => {
            signal = request.signal
            clientQueryId = ((await request.json()) as { client_query_id: string }).client_query_id
            markSent()
            return await new Promise(() => {})
        })
        dataChecks.mockImplementation(answer([200, checksOf('passed')]))
        turnTheFlagOn()
        await sent

        await expectLogic(logic, () => vizData.actions.loadData()).toFinishAllListeners()

        expect(signal?.aborted).toBe(true)
        expect(cancelledQueryIds).toEqual([clientQueryId])
        expect(dataChecks).toHaveBeenCalledTimes(2)
        expect(logic.values.status).toBe('passed')
        expect(loadedEvents().map((properties) => properties.status)).toEqual(['cancelled', 'passed'])
    })

    it.each([
        [
            'a run with findings',
            200,
            { ...checksOf('warning'), checks: [{ key: 'bot_traffic', level: 'warning' }] },
            { status: 'warning', findings: ['bot_traffic'] },
        ],
        ['a run the server could not finish', 500, { detail: 'No.' }, { status: 'failed', findings: [] }],
        ['a run the person may not see', 403, { detail: 'No.' }, { status: 'unavailable', findings: [] }],
    ])('reports how %s ended', async (_name, responseStatus, response, expected) => {
        dataChecks.mockImplementation(answer([responseStatus, response]))

        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        expect(loadedEvents()).toEqual([{ ...expected, duration_ms: expect.any(Number) }])
    })

    it('turns the filter on for the insight from the checks, then checks the filtered chart', async () => {
        dataChecks.mockImplementation(answer([200, checksOf('warning')]))
        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        await expectLogic(logic, () =>
            logic.actions.setFiltersTestAccounts(true, 'internal_users')
        ).toFinishAllListeners()

        expect(vizData.values.querySource?.filterTestAccounts).toBe(true)
        expect(sentSources.map((source) => !!source.filterTestAccounts)).toEqual([false, true])
    })

    const rule = { key: 'email', type: 'person', operator: 'is_not', value: ['qa@example.com'] }
    const addTheRule = (): void => {
        logic.actions.addFilterRule({ key: 'internal_users', filter_to_add: rule } as InsightDataCheckApi)
    }
    it("adds the check's rule to this insight's filters once, then checks the filtered chart", async () => {
        dataChecks.mockImplementation(answer([200, checksOf('warning')]))
        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()
        const check = { key: 'internal_users', filter_to_add: rule } as InsightDataCheckApi

        await expectLogic(logic, () => {
            logic.actions.excludeFromInsight(check)
            logic.actions.excludeFromInsight(check)
        }).toFinishAllListeners()

        expect(vizData.values.querySource?.properties).toEqual([rule])
        expect(sentSources.at(-1)?.properties).toEqual([rule])
        expect(dataChecks).toHaveBeenCalledTimes(2)
    })

    it("adds the check's rule to the project's filter, then checks again", async () => {
        const existing = teamLogic.values.currentTeam?.test_account_filters ?? []
        dataChecks.mockImplementation(answer([200, checksOf('warning')]))
        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        await expectLogic(logic, addTheRule).toFinishAllListeners()

        expect(savedFilters).toEqual([[...existing, rule]])
        expect(dataChecks).toHaveBeenCalledTimes(2)
    })

    it('refreshes a chart that applies the filter once a rule is added, so it drops the excluded events', async () => {
        dataChecks.mockImplementation(answer([200, checksOf('warning')]))
        vizData.actions.updateQuerySource({ filterTestAccounts: true })
        await expectLogic(logic, turnTheFlagOn).toFinishAllListeners()

        await expectLogic(logic, addTheRule).toDispatchActions(vizData, [
            (action) =>
                action.type === vizData.actionTypes.loadData && String(action.payload.refresh).startsWith('force'),
        ])
    })
})
