import { expectLogic } from 'kea-test-utils'

import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricsVariableOptionsCreate } from 'products/metrics/frontend/generated/api'

import { dashboardMetricVariablesLogic } from './dashboardMetricVariablesLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    metricsVariableOptionsCreate: jest.fn(),
}))

const mockOptions = metricsVariableOptionsCreate as jest.MockedFunction<typeof metricsVariableOptionsCreate>

const variables: MetricsDashboardVariable[] = [
    { name: 'service', source: 'custom', customValues: ['api', 'worker'], current: { values: ['api'] } },
    { name: 'route', source: 'sql', query: 'SELECT route WHERE service = $service', current: { values: ['/a'] } },
]

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

function deferred(): { promise: Promise<{ results: string[] }>; resolve: (results: string[]) => void } {
    let resolve: (results: string[]) => void = () => {}
    const promise = new Promise<{ results: string[] }>((done) => {
        resolve = (results) => done({ results })
    })
    return { promise, resolve }
}

describe('dashboardMetricVariablesLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('keeps a selection the user makes while a background query finishes', async () => {
        const zone = deferred()
        mockOptions.mockImplementation(async (_team, body) => {
            if (body.query === 'SELECT zone') {
                return zone.promise
            }
            return { results: ['/a', '/b', '/c'] }
        })
        const withZone: MetricsDashboardVariable[] = [
            ...variables,
            { name: 'zone', source: 'sql', query: 'SELECT zone', current: { values: ['eu'] } },
        ]
        // The dashboard passes each published selection back in as props, as `DashboardMetricVariables` does.
        const onSelectionsChange = jest.fn((next: MetricsDashboardVariable[]) => {
            dashboardMetricVariablesLogic({ dashboardId: 1, variables: next, onSelectionsChange })
        })
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables: withZone, onSelectionsChange })
        logic.mount()
        await flush()
        logic.actions.select('service', { values: ['worker'] })
        await flush()
        logic.actions.select('route', { values: ['/c'] })
        await flush()

        zone.resolve(['us'])
        await expectLogic(logic).toFinishAllListeners()

        const last = onSelectionsChange.mock.calls.at(-1)?.[0] as MetricsDashboardVariable[]
        expect(last.map((variable) => variable.current)).toEqual([
            { values: ['worker'] },
            { values: ['/c'] },
            { values: ['us'] },
        ])
    })

    it('waits for a dependent that is still loading before it publishes another change', async () => {
        mockOptions.mockResolvedValue({ results: ['/a'] })
        const onSelectionsChange = jest.fn()
        const withText: MetricsDashboardVariable[] = [
            ...variables,
            { name: 'env', source: 'textbox', current: { values: ['prod'] } },
        ]
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables: withText, onSelectionsChange })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const routes = deferred()
        mockOptions.mockReturnValue(routes.promise)
        logic.actions.select('service', { values: ['worker'] })
        await flush()
        logic.actions.select('env', { values: ['dev'] })
        await flush()
        expect(onSelectionsChange).not.toHaveBeenCalled()

        routes.resolve(['/b'])
        await expectLogic(logic).toFinishAllListeners()
        expect(onSelectionsChange).toHaveBeenCalledTimes(1)
        expect(
            onSelectionsChange.mock.calls[0][0].map((variable: MetricsDashboardVariable) => variable.current)
        ).toEqual([{ values: ['worker'] }, { values: ['/b'] }, { values: ['dev'] }])
    })

    it('loads a changed definition before it publishes it', async () => {
        mockOptions.mockResolvedValue({ results: ['/a'] })
        const onSelectionsChange = jest.fn()
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables, onSelectionsChange })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        mockOptions.mockResolvedValue({ results: ['/z'] })
        const redefined = [variables[0], { ...variables[1], query: 'SELECT other_route WHERE service = $service' }]
        logic.actions.stage(redefined, ['route'])
        await expectLogic(logic).toFinishAllListeners()

        expect(onSelectionsChange).toHaveBeenCalledTimes(1)
        expect(onSelectionsChange.mock.calls[0][0][1]).toEqual({ ...redefined[1], current: { values: ['/z'] } })
    })

    it('drops a pending selection when the dashboard discards it', async () => {
        mockOptions.mockResolvedValue({ results: ['/b'] })
        const onSelectionsChange = jest.fn((next: MetricsDashboardVariable[]) => {
            dashboardMetricVariablesLogic({ dashboardId: 1, variables: next, onSelectionsChange })
        })
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables, onSelectionsChange })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.select('service', { values: ['worker'] })
        await expectLogic(logic).toFinishAllListeners()

        const routes = deferred()
        mockOptions.mockReturnValue(routes.promise)
        logic.actions.select('service', { values: ['web'] })
        await flush()
        dashboardMetricVariablesLogic({ dashboardId: 1, variables, onSelectionsChange })
        routes.resolve(['/c'])
        await expectLogic(logic).toFinishAllListeners()

        const services = onSelectionsChange.mock.calls.map(([next]) => next[0].current?.values[0])
        expect(services).not.toContain('web')
        expect(logic.values.pendingVariables).toBeNull()
    })

    it('sends one request for variables with the same query and selections', async () => {
        mockOptions.mockReturnValue(new Promise(() => {}))
        const same: MetricsDashboardVariable[] = [
            { name: 'a', source: 'sql', query: 'SELECT 1' },
            { name: 'b', source: 'sql', query: 'SELECT 1' },
        ]
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables: same, onSelectionsChange: jest.fn() })
        logic.mount()
        await flush()

        expect(mockOptions).toHaveBeenCalledTimes(1)
    })

    it('sends no queued option request after the dashboard closes', async () => {
        const first = deferred()
        mockOptions.mockReturnValueOnce(first.promise).mockReturnValue(new Promise(() => {}))
        const many: MetricsDashboardVariable[] = Array.from({ length: 6 }, (_, index) => ({
            name: `v${index}`,
            source: 'sql',
            query: `SELECT ${index}`,
        }))
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables: many, onSelectionsChange: jest.fn() })
        logic.mount()
        await flush()
        logic.unmount()

        first.resolve(['a'])
        await flush()
        await flush()

        expect(mockOptions).toHaveBeenCalledTimes(4)
    })

    it('keeps loading options when the dashboard restores other selections', async () => {
        const zone = deferred()
        mockOptions.mockImplementation(async (_team, body) =>
            body.query === 'SELECT zone' ? zone.promise : { results: [] }
        )
        const withZone: MetricsDashboardVariable[] = [
            { name: 'env', source: 'textbox', current: { values: ['prod'] } },
            { name: 'zone', source: 'sql', query: 'SELECT zone' },
        ]
        const props = { dashboardId: 1, variables: withZone, onSelectionsChange: jest.fn() }
        const logic = dashboardMetricVariablesLogic(props)
        logic.mount()
        await flush()

        dashboardMetricVariablesLogic({
            ...props,
            variables: [{ ...withZone[0], current: { values: ['dev'] } }, withZone[1]],
        })
        await flush()
        zone.resolve(['eu'])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.options.zone).toEqual(['eu'])
        expect(logic.values.loadingNames).toEqual([])
    })

    it('publishes a reconciled selection after another change takes over the load', async () => {
        const zone = deferred()
        mockOptions.mockImplementation(async (_team, body) => {
            if (body.query === 'SELECT zone WHERE route = $route') {
                return zone.promise
            }
            return { results: body.variables?.some((other) => other.values.includes('worker')) ? ['/b'] : ['/a'] }
        })
        const chain: MetricsDashboardVariable[] = [
            ...variables,
            { name: 'zone', source: 'sql', query: 'SELECT zone WHERE route = $route', current: { values: ['eu'] } },
            { name: 'env', source: 'textbox', current: { values: ['prod'] } },
        ]
        const onSelectionsChange = jest.fn((next: MetricsDashboardVariable[]) => {
            dashboardMetricVariablesLogic({ dashboardId: 1, variables: next, onSelectionsChange })
        })
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables: chain, onSelectionsChange })
        logic.mount()
        zone.resolve(['eu'])
        await expectLogic(logic).toFinishAllListeners()

        const zoneAgain = deferred()
        mockOptions.mockImplementation(async (_team, body) => {
            if (body.query === 'SELECT zone WHERE route = $route') {
                return zoneAgain.promise
            }
            return { results: body.variables?.some((other) => other.values.includes('worker')) ? ['/b'] : ['/a'] }
        })
        logic.actions.select('service', { values: ['worker'] })
        await flush()
        logic.actions.select('env', { values: ['dev'] })
        await flush()
        zoneAgain.resolve(['eu'])
        await expectLogic(logic).toFinishAllListeners()

        const last = onSelectionsChange.mock.calls.at(-1)?.[0] as MetricsDashboardVariable[]
        expect(last.map((variable) => variable.current)).toEqual([
            { values: ['worker'] },
            { values: ['/b'] },
            { values: ['eu'] },
            { values: ['dev'] },
        ])
    })

    it('reloads the dependents of a staged definition when its parent changes', async () => {
        mockOptions.mockImplementation(async (_team, body) => ({
            results: body.variables?.some((other) => other.values.includes('worker')) ? ['/b'] : ['/a'],
        }))
        const independent: MetricsDashboardVariable[] = [
            variables[0],
            { name: 'route', source: 'sql', query: 'SELECT route', current: { values: ['/a'] } },
        ]
        const logic = dashboardMetricVariablesLogic({
            dashboardId: 1,
            variables: independent,
            onSelectionsChange: jest.fn(),
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setPendingVariables(variables)
        mockOptions.mockClear()

        logic.actions.select('service', { values: ['worker'] })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockOptions.mock.calls.map(([, body]) => body.query)).toEqual([variables[1].query])
    })

    it('runs at most four option requests at once', async () => {
        const many: MetricsDashboardVariable[] = Array.from({ length: 6 }, (_, index) => ({
            name: `v${index}`,
            source: 'sql',
            query: `SELECT ${index}`,
        }))
        mockOptions.mockReturnValue(new Promise(() => {}))
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables: many, onSelectionsChange: jest.fn() })
        logic.mount()
        await flush()

        expect(mockOptions).toHaveBeenCalledTimes(4)
    })

    it('publishes a parent selection once, with the selections of its dependents reconciled', async () => {
        mockOptions.mockResolvedValue({ results: ['/a'] })
        const onSelectionsChange = jest.fn()
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables, onSelectionsChange })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        mockOptions.mockResolvedValue({ results: ['/b'] })
        logic.actions.select('service', { values: ['worker'] })
        await expectLogic(logic).toFinishAllListeners()

        expect(onSelectionsChange).toHaveBeenCalledTimes(1)
        expect(
            onSelectionsChange.mock.calls[0][0].map((variable: MetricsDashboardVariable) => variable.current)
        ).toEqual([{ values: ['worker'] }, { values: ['/b'] }])
    })

    it('publishes a selection without waiting for an unrelated slow query, and does not send that query again', async () => {
        let finishZone: (value: { results: string[] }) => void = () => {}
        const zone = new Promise<{ results: string[] }>((resolve) => {
            finishZone = resolve
        })
        mockOptions.mockImplementation(async (_team, body) => {
            if (body.query?.includes('zone')) {
                return zone
            }
            return { results: body.variables?.some((other) => other.values.includes('worker')) ? ['/b'] : ['/a'] }
        })
        const onSelectionsChange = jest.fn()
        const zoneVariable: MetricsDashboardVariable = {
            name: 'zone',
            source: 'sql',
            query: 'SELECT zone',
            current: { values: ['eu'] },
        }
        const logic = dashboardMetricVariablesLogic({
            dashboardId: 1,
            variables: [...variables, zoneVariable],
            onSelectionsChange,
        })
        logic.mount()
        await new Promise((resolve) => setTimeout(resolve, 0))

        logic.actions.select('service', { values: ['worker'] })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(onSelectionsChange).toHaveBeenCalledTimes(1)
        expect(mockOptions.mock.calls.filter(([, body]) => body.query === 'SELECT zone')).toHaveLength(1)
        finishZone({ results: ['eu'] })
        await expectLogic(logic).toFinishAllListeners()
    })
})
