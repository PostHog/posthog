import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseJobStatsRetrieve: jest.fn(),
    dataWarehouseTotalRowsStatsRetrieve: jest.fn(),
    dataWarehouseDataHealthIssuesRetrieve: jest.fn(),
    dataWarehouseCompletedActivityRetrieve: jest.fn(),
}))

jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataDestinationsList: jest.fn(),
    externalDataSourcesList: jest.fn(),
}))

jest.mock('lib/components/AppMetrics/appMetricsLogic', () => ({
    loadAppMetricsTimeSeries: jest.fn(),
}))

const api = jest.requireMock('products/data_warehouse/frontend/generated/api')
const wsApi = jest.requireMock('products/warehouse_sources/frontend/generated/api')
const metrics = jest.requireMock('lib/components/AppMetrics/appMetricsLogic')

const issue = (overrides: Record<string, any> = {}): Record<string, any> => ({
    id: 'issue-1',
    name: 'charges',
    type: 'external_data_sync',
    status: 'failed',
    error: 'it broke',
    failed_at: '2026-09-25T10:00:00Z',
    url: '/data-management/sources/1',
    ...overrides,
})

describe('pipelineOverviewSceneLogic', () => {
    let logic: ReturnType<typeof pipelineOverviewSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        api.dataWarehouseJobStatsRetrieve.mockResolvedValue({ days: 7, total_jobs: 0 })
        api.dataWarehouseTotalRowsStatsRetrieve.mockResolvedValue({ total_rows: 0 })
        api.dataWarehouseDataHealthIssuesRetrieve.mockResolvedValue({ results: [], count: 0 })
        api.dataWarehouseCompletedActivityRetrieve.mockResolvedValue({ results: [], next: null, previous: null })
        wsApi.externalDataDestinationsList.mockResolvedValue({ results: [] })
        wsApi.externalDataSourcesList.mockResolvedValue({ results: [] })
        metrics.loadAppMetricsTimeSeries.mockResolvedValue({ labels: [], interval: 'day', timezone: 'UTC', series: [] })
        logic = pipelineOverviewSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it('has answered nothing while its loaders are still in flight', () => {
        // `null` rather than an empty list, so the scene can tell "not asked yet" from "nothing
        // is wrong" and never renders the healthy state over a pending load.
        logic.unmount()
        // A promise the test never settles, so the in-flight state can be asserted rather than raced.
        api.dataWarehouseDataHealthIssuesRetrieve.mockReturnValue(new Promise(() => {}))
        api.dataWarehouseJobStatsRetrieve.mockReturnValue(new Promise(() => {}))

        logic.mount()

        expect(logic.values.healthIssues).toBeNull()
        expect(logic.values.jobStats).toBeNull()
        expect(logic.values.loadingFirstTime).toBe(true)
    })

    it('orders issues worst first', async () => {
        // The point of the section is that the worst pipeline is the one you see, whatever order
        // the endpoint happened to return.
        api.dataWarehouseDataHealthIssuesRetrieve.mockResolvedValue({
            count: 4,
            results: [
                issue({ id: 'a', status: 'disabled' }),
                issue({ id: 'b', status: 'degraded' }),
                issue({ id: 'c', status: 'failed' }),
                issue({ id: 'd', status: 'billing_limit' }),
            ],
        })

        await expectLogic(logic, () => logic.actions.loadHealthIssues()).toFinishAllListeners()

        expect(logic.values.issuesBySeverity.map((i: any) => i.status)).toEqual([
            'failed',
            'billing_limit',
            'degraded',
            'disabled',
        ])
    })

    it('counts only syncs as failing syncs', async () => {
        // The tile says "of them syncs", so a failed materialized view must not inflate it.
        api.dataWarehouseDataHealthIssuesRetrieve.mockResolvedValue({
            count: 2,
            results: [issue({ id: 'a' }), issue({ id: 'b', type: 'materialized_view' })],
        })

        await expectLogic(logic, () => logic.actions.loadHealthIssues()).toFinishAllListeners()

        expect(logic.values.failingSyncCount).toEqual(1)
    })

    it('keeps only import issues in the health list', async () => {
        // The endpoint answers for the whole warehouse. Its `destination` type is a batch export
        // or a CDP destination, not a warehouse destination, so showing it here would label
        // another product's failure as one of this scene's pipelines.
        api.dataWarehouseDataHealthIssuesRetrieve.mockResolvedValue({
            count: 5,
            results: [
                issue({ id: 'a', type: 'materialized_view' }),
                issue({ id: 'b', type: 'external_data_sync' }),
                issue({ id: 'c', type: 'destination' }),
                issue({ id: 'd', type: 'source' }),
                issue({ id: 'e', type: 'transformation' }),
            ],
        })

        await expectLogic(logic, () => logic.actions.loadHealthIssues()).toFinishAllListeners()

        expect(logic.values.issuesBySeverity.map((i: any) => i.id).sort()).toEqual(['b', 'd'])
    })

    it('leaves materialized view runs out of the failures list', async () => {
        api.dataWarehouseCompletedActivityRetrieve.mockResolvedValue({
            next: null,
            previous: null,
            results: [
                { id: 'r1', type: 'Materialized view', name: 'account_activity', status: 'Failed' },
                { id: 'r2', type: 'Stripe', name: 'charges', status: 'Failed' },
            ],
        })

        await expectLogic(logic, () => logic.actions.loadRecentFailures()).toFinishAllListeners()

        expect(logic.values.failedRuns.map((r: any) => r.id)).toEqual(['r2'])
    })

    it('asks for failed runs, not completed ones', async () => {
        // Without the outcome parameter this endpoint returns successes, so the failures section
        // would quietly list runs that worked.
        await expectLogic(logic, () => logic.actions.loadRecentFailures()).toFinishAllListeners()

        expect(api.dataWarehouseCompletedActivityRetrieve).toHaveBeenCalledWith(
            expect.anything(),
            expect.objectContaining({ outcome: 'failed' })
        )
    })

    it('leaves the billing-period row total alone when the window changes', async () => {
        // Rows are per billing period and health is current state, so refetching them on a window
        // change would be three wasted requests per click.
        api.dataWarehouseJobStatsRetrieve.mockClear()
        api.dataWarehouseTotalRowsStatsRetrieve.mockClear()

        await expectLogic(logic, () => logic.actions.setWindow(30)).toFinishAllListeners()

        expect(logic.values.window).toEqual(30)
        expect(api.dataWarehouseJobStatsRetrieve).toHaveBeenCalledWith(
            expect.anything(),
            expect.objectContaining({ days: 30 })
        )
        expect(api.dataWarehouseTotalRowsStatsRetrieve).not.toHaveBeenCalled()
    })

    it('refresh reloads everything', async () => {
        api.dataWarehouseJobStatsRetrieve.mockClear()
        api.dataWarehouseTotalRowsStatsRetrieve.mockClear()
        api.dataWarehouseDataHealthIssuesRetrieve.mockClear()
        api.dataWarehouseCompletedActivityRetrieve.mockClear()

        await expectLogic(logic, () => logic.actions.refresh()).toFinishAllListeners()

        expect(api.dataWarehouseJobStatsRetrieve).toHaveBeenCalled()
        expect(api.dataWarehouseTotalRowsStatsRetrieve).toHaveBeenCalled()
        expect(api.dataWarehouseDataHealthIssuesRetrieve).toHaveBeenCalled()
        expect(api.dataWarehouseCompletedActivityRetrieve).toHaveBeenCalled()
    })

    it('asks for each destination by id rather than one breakdown over every instance', async () => {
        // The breakdown is capped at 100 rows. A team with thousands of tables pushes every
        // destination out of that cap, which emptied the chart on a real project.
        logic.unmount()
        wsApi.externalDataDestinationsList.mockResolvedValue({
            results: [
                { id: 'dest-1', name: 'PostHog warehouse', type: 'PostHogWarehouse' },
                { id: 'dest-2', name: 'Analytics Postgres', type: 'Postgres' },
            ],
        })
        metrics.loadAppMetricsTimeSeries.mockResolvedValue({
            labels: ['2026-09-27', '2026-09-28'],
            interval: 'day',
            timezone: 'UTC',
            series: [{ name: 'rows_synced', values: [10, 20] }],
        })

        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const asked = metrics.loadAppMetricsTimeSeries.mock.calls.map(([request]: any[]) => request)
        expect(asked.map((r: any) => r.instanceId).sort()).toEqual(['dest-1', 'dest-2'])
        expect(asked.every((r: any) => r.breakdownBy === undefined)).toBe(true)
        // Both bounds go straight into `toDateTime(...)`, so a relative string or a missing
        // `dateTo` makes the query throw instead of returning rows.
        asked.forEach((r: any) => {
            expect(Date.parse(r.dateFrom)).not.toBeNaN()
            expect(Date.parse(r.dateTo)).not.toBeNaN()
            expect(Date.parse(r.dateFrom)).toBeLessThan(Date.parse(r.dateTo))
        })
        expect(logic.values.rowsByDestination.map((s: any) => s.label)).toEqual([
            'PostHog warehouse',
            'Analytics Postgres',
        ])
    })

    it('leaves webhook tables out of the health list', async () => {
        // A webhook table is pushed to on the vendor's schedule, never pulled on ours, so it has
        // no last sync and cannot have stopped. A real project had 16 of them crowding the list.
        api.dataWarehouseDataHealthIssuesRetrieve.mockResolvedValue({
            count: 2,
            results: [
                issue({ id: 'a', type: 'external_data_sync', sync_type: 'webhook' }),
                issue({ id: 'b', type: 'external_data_sync', sync_type: 'incremental' }),
            ],
        })

        await expectLogic(logic, () => logic.actions.loadHealthIssues()).toFinishAllListeners()

        expect(logic.values.issuesBySeverity.map((i: any) => i.id)).toEqual(['b'])
    })

    it('asks the runs endpoint for imports only', async () => {
        // The endpoint answers for the whole warehouse and pages by time. A team with enough
        // failing views filled every page with them, so this list rendered empty.
        await expectLogic(logic).toFinishAllListeners()

        expect(api.dataWarehouseCompletedActivityRetrieve).toHaveBeenCalledWith(
            expect.anything(),
            expect.objectContaining({ outcome: 'failed', kind: 'import' })
        )
    })

    it('counts only the tables switched on across every page', async () => {
        logic.unmount()
        wsApi.externalDataSourcesList.mockReset()
        wsApi.externalDataSourcesList
            .mockResolvedValueOnce({
                next: '/api/projects/1/external_data_sources/?limit=100&offset=2',
                results: [
                    { id: 'a', schemas: [{ should_sync: true }, { should_sync: false }] },
                    { id: 'b', schemas: [] },
                ],
            })
            .mockResolvedValueOnce({
                next: null,
                results: [{ id: 'c', schemas: [{ should_sync: true }, { should_sync: true }] }],
            })

        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.syncingTableCount).toEqual(3)
        expect(wsApi.externalDataSourcesList).toHaveBeenNthCalledWith(1, expect.anything(), { limit: 100, offset: 0 })
        expect(wsApi.externalDataSourcesList).toHaveBeenNthCalledWith(2, expect.anything(), { limit: 100, offset: 2 })
    })
})
