import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsPatternsCreate } from 'products/logs/frontend/generated/api'
import type { _LogsPatternsResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { logsPatternsLogic } from './logsPatternsLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsPatternsCreate: jest.fn(),
}))

const mockCreate = logsPatternsCreate as jest.MockedFunction<typeof logsPatternsCreate>

const ID = 'test-viewer'

const RESPONSE: _LogsPatternsResponseApi = {
    patterns: [
        {
            pattern: 'User <*> not found',
            count: 3,
            volume_share_pct: 75,
            error_count: 3,
            first_seen: '2026-06-23T12:00:00+00:00',
            last_seen: '2026-06-23T12:05:00+00:00',
            examples: [],
            services: ['auth'],
        },
    ],
    scanned_count: 3,
    total_count: 3,
    sampled: false,
}

describe('logsPatternsLogic', () => {
    let logic: ReturnType<typeof logsPatternsLogic.build>
    let filtersLogic: ReturnType<typeof logsViewerFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockCreate.mockResolvedValue(RESPONSE)
        filtersLogic = logsViewerFiltersLogic({ id: ID })
        filtersLogic.mount()
        logic = logsPatternsLogic({ id: ID })
    })

    it('loads patterns on mount from the shared viewer filters', async () => {
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadPatterns', 'loadPatternsSuccess'])
            .toMatchValues({ patterns: RESPONSE.patterns })

        expect(mockCreate).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                query: expect.objectContaining({ severityLevels: [], serviceNames: [] }),
            })
        )
    })

    it('reloads when a shared filter changes', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])
        mockCreate.mockClear()

        await expectLogic(logic, () => {
            filtersLogic.actions.setSeverityLevels(['error'])
        }).toDispatchActions(['setSeverityLevels', 'loadPatterns', 'loadPatternsSuccess'])

        expect(mockCreate).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ query: expect.objectContaining({ severityLevels: ['error'] }) })
        )
    })
})
