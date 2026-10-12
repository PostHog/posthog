import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { metricsDashboardImportsCreate, metricsDashboardImportsList } from 'products/metrics/frontend/generated/api'
import type {
    DashboardImportApi,
    DashboardImportCreateApi,
    DashboardImportSourceEnumApi,
} from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from './metricsDashboardImportLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsDashboardImportsCreate: jest.fn(),
    metricsDashboardImportsList: jest.fn(),
}))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockCreate = jest.mocked(metricsDashboardImportsCreate)
const mockList = jest.mocked(metricsDashboardImportsList)

const importStatus = (overrides: Partial<DashboardImportApi> = {}): DashboardImportApi => ({
    id: '0b5e7c3a-2f1d-4c8e-9a6b-3d2f1e0c9b8a',
    source: 'grafana',
    status: 'running',
    dashboard_name: 'Checkout service',
    phase: null,
    panel_progress: [],
    layout_rounds: null,
    layout_round: null,
    dashboard_id: null,
    error: null,
    summary: null,
    panels: [],
    ...overrides,
})

const COMPLETED = importStatus({
    status: 'completed',
    dashboard_id: 7,
    summary: { total: 3, imported: 2, approximated: 0, failed: 1, skipped: 0 },
})

describe('metricsDashboardImportLogic', () => {
    let logic: ReturnType<typeof metricsDashboardImportLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockCreate.mockReset()
        mockList.mockReset().mockResolvedValue([])
        jest.mocked(lemonToast.success).mockReset()
        jest.mocked(lemonToast.error).mockReset()
        logic = metricsDashboardImportLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    it.each<[DashboardImportSourceEnumApi, () => void, DashboardImportCreateApi]>([
        [
            'grafana',
            () => logic.actions.setGrafanaJson('{"panels": []}'),
            { source: 'grafana', grafana_json: '{"panels": []}' },
        ],
        [
            'screenshot',
            () => logic.actions.setScreenshot('data:image/png;base64,iVBORw0KGgo='),
            { source: 'screenshot', image_base64: 'iVBORw0KGgo=' },
        ],
    ])('a %s import sends one request, without a data URL prefix or a blank name', async (source, fill, body) => {
        mockCreate.mockResolvedValue(COMPLETED)
        logic.actions.openImportModal(source)
        fill()
        logic.actions.setDashboardName('  ')

        await expectLogic(logic, () => {
            logic.actions.startImport()
            logic.actions.startImport()
        }).toDispatchActions(['startImportSuccess'])

        expect(mockCreate).toHaveBeenCalledTimes(1)
        expect(mockCreate.mock.calls[0][1]).toEqual(body)
        expect(logic.values.step).toBe('summary')
    })

    it.each<[string, DashboardImportApi, () => void]>([
        ['completes', COMPLETED, () => expect(lemonToast.success).toHaveBeenCalledTimes(1)],
        [
            'fails',
            importStatus({ status: 'failed', error: 'The agent run failed.' }),
            () => expect(lemonToast.error).toHaveBeenCalledTimes(1),
        ],
    ])('polls the recent imports while one runs, and tells the user when it %s', async (_, ended, expectMessage) => {
        jest.useFakeTimers()
        mockCreate.mockResolvedValue(importStatus())
        // The refresh right after the start fails, so only the poll can bring the next status.
        mockList.mockRejectedValueOnce(new Error('Bad gateway'))
        logic.actions.openImportModal('grafana')
        logic.actions.setGrafanaJson('{"panels": []}')
        logic.actions.startImport()
        await jest.advanceTimersByTimeAsync(0)
        logic.actions.closeImportModal()

        mockList.mockResolvedValue([importStatus({ phase: 'matching' })])
        await jest.advanceTimersByTimeAsync(5000)
        expect(logic.values.runningImports.map((item) => item.phase)).toEqual(['matching'])

        mockList.mockResolvedValue([ended])
        await jest.advanceTimersByTimeAsync(5000)
        expect(logic.values.runningImports).toEqual([])
        expectMessage()

        const calls = mockList.mock.calls.length
        await jest.advanceTimersByTimeAsync(30000)
        expect(mockList).toHaveBeenCalledTimes(calls)
    })

    it('blocks a fourth import while three run', async () => {
        mockList.mockResolvedValue(['a', 'b', 'c'].map((id) => importStatus({ id })))
        await expectLogic(logic, () => logic.actions.loadRecentImports()).toDispatchActions(['setRecentImports'])
        logic.actions.openImportModal('grafana')
        logic.actions.setGrafanaJson('{"panels": []}')

        expect(logic.values.importDisabledReason).toBe('3 imports are running. Wait for one of them to finish.')
    })
})
