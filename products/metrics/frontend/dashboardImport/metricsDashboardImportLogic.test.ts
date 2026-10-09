import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { metricsDashboardImportsCreate, metricsDashboardImportsRetrieve } from 'products/metrics/frontend/generated/api'
import type {
    DashboardImportApi,
    DashboardImportCreateApi,
    DashboardImportSourceEnumApi,
} from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from './metricsDashboardImportLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsDashboardImportsCreate: jest.fn(),
    metricsDashboardImportsRetrieve: jest.fn(),
}))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockCreate = jest.mocked(metricsDashboardImportsCreate)
const mockRetrieve = jest.mocked(metricsDashboardImportsRetrieve)

const IMPORT_ID = '0b5e7c3a-2f1d-4c8e-9a6b-3d2f1e0c9b8a'

const importStatus = (overrides: Partial<DashboardImportApi> = {}): DashboardImportApi => ({
    id: IMPORT_ID,
    source: 'grafana',
    status: 'running',
    dashboard_name: 'Checkout service',
    progress: null,
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

    const startRunningImport = (): void => {
        mockCreate.mockResolvedValue(importStatus())
        logic.actions.openImportModal('grafana')
        logic.actions.setGrafanaJson('{"panels": []}')
        logic.actions.startImport()
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        mockCreate.mockReset()
        mockRetrieve.mockReset()
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
        // An import that ends in the request shows its summary at once and has nothing to poll.
        expect(logic.values.step).toBe('summary')
        expect(logic.values.activeImport).toBeNull()
    })

    it.each<[string, () => void, string, () => void]>([
        [
            'completes',
            () => mockRetrieve.mockResolvedValue(COMPLETED),
            'summary',
            () => expect(lemonToast.success).toHaveBeenCalledTimes(1),
        ],
        [
            'fails',
            () => mockRetrieve.mockResolvedValue(importStatus({ status: 'failed', error: 'The agent run failed.' })),
            'summary',
            () => expect(lemonToast.error).toHaveBeenCalledTimes(1),
        ],
        [
            'is gone',
            () => mockRetrieve.mockRejectedValue(new ApiError('Not found.', 404)),
            'input',
            () => expect(lemonToast.success).not.toHaveBeenCalled(),
        ],
    ])('polls a running import until it %s, then stops', async (_, settle, finalStep, expectMessage) => {
        jest.useFakeTimers()
        startRunningImport()
        await jest.advanceTimersByTimeAsync(0)
        logic.actions.closeImportModal()
        expect(logic.values.step).toBe('progress')

        mockRetrieve.mockResolvedValue(importStatus({ progress: 'Matched 1 of 3 panels.' }))
        await jest.advanceTimersByTimeAsync(5000)
        expect(logic.values.currentImport?.progress).toBe('Matched 1 of 3 panels.')

        settle()
        await jest.advanceTimersByTimeAsync(5000)
        expect(logic.values.step).toBe(finalStep)
        expect(logic.values.activeImport).toBeNull()
        expectMessage()

        await jest.advanceTimersByTimeAsync(30000)
        expect(mockRetrieve).toHaveBeenCalledTimes(2)
    })

    it('finds the import that runs after a remount, and shows no form before its status arrives', async () => {
        startRunningImport()
        await expectLogic(logic).toDispatchActions(['startImportSuccess'])
        logic.unmount()

        mockRetrieve.mockResolvedValue(COMPLETED)
        logic = metricsDashboardImportLogic()
        logic.mount()
        expect(logic.values.step).toBe('progress')

        await expectLogic(logic).toDispatchActions(['setCurrentImport'])
        expect(mockRetrieve).toHaveBeenCalledWith(expect.any(String), IMPORT_ID)
        expect(logic.values.step).toBe('summary')
        expect(lemonToast.success).toHaveBeenCalledTimes(1)
    })
})
