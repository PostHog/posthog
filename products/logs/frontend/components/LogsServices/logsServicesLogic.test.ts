import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsServicesCreate } from 'products/logs/frontend/generated/api'
import type { _LogsServicesResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { logsServicesLogic } from './logsServicesLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsServicesCreate: jest.fn(),
}))

// 30 services (2 pages of 25): svc-1..svc-29 by descending volume, plus the
// backend's placeholder name for empty service_name as the lowest-volume row.
const SERVICES = Array.from({ length: 30 }, (_, i) => ({
    service_name: i === 29 ? '(no service)' : `svc-${i + 1}`,
    log_count: 1000 - i,
    error_count: 0,
    error_rate: 0,
}))

const INITIAL_RESPONSE: _LogsServicesResponseApi = {
    services: SERVICES,
    // The backend sparklines only the top services of the response.
    sparkline: SERVICES.slice(0, 25).map((s) => ({
        time: '2026-08-12T00:00:00Z',
        service_name: s.service_name,
        count: 1,
    })),
    total_services: 30,
}

// A page-turn response is only read for its sparkline; names arrive with the
// backend's "(no service)" placeholder already applied, same as the initial load.
const PAGE_2_SPARKLINE_RESPONSE: _LogsServicesResponseApi = {
    services: [],
    sparkline: SERVICES.slice(25).map((s) => ({
        time: '2026-08-12T00:00:00Z',
        service_name: s.service_name,
        count: 1,
    })),
    total_services: 0,
}

describe('logsServicesLogic', () => {
    let logic: ReturnType<typeof logsServicesLogic.build>

    beforeEach(() => {
        jest.mocked(logsServicesCreate).mockReset()
        jest.mocked(logsServicesCreate).mockResolvedValueOnce(INITIAL_RESPONSE)
        jest.mocked(logsServicesCreate).mockResolvedValue(PAGE_2_SPARKLINE_RESPONSE)
        initKeaTests()
        logic = logsServicesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('fetches sparklines only for services the initial response did not cover, once', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logsServicesCreate).toHaveBeenCalledTimes(1)

        await expectLogic(logic, () => {
            logic.actions.setPage(2)
        }).toFinishAllListeners()

        expect(logsServicesCreate).toHaveBeenCalledTimes(2)
        const [, secondCall] = jest.mocked(logsServicesCreate).mock.calls
        // Page 2 holds the 5 lowest-volume rows; the placeholder name maps back
        // to the empty string the backend stores.
        expect(secondCall[1].query.serviceNames).toEqual(['svc-26', 'svc-27', 'svc-28', 'svc-29', ''])
        expect(logic.values.sparklineByService['(no service)']).toBeTruthy()

        // Revisiting an already-fetched page must not refetch.
        await expectLogic(logic, () => {
            logic.actions.setPage(1)
            logic.actions.setPage(2)
        }).toFinishAllListeners()
        expect(logsServicesCreate).toHaveBeenCalledTimes(2)
    })

    it('search reloads aggregates with the term and resets to page 1', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setPage(2)

        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('api')
        }).toDispatchActions(['setSearchTerm', 'setPage', 'loadServicesData', 'loadServicesDataSuccess'])

        expect(logic.values.page).toBe(1)
        const lastCall = jest.mocked(logsServicesCreate).mock.calls.at(-1)
        expect(lastCall?.[1].query.serviceNameSearch).toBe('api')
    })
})
