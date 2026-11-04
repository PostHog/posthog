import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsNaturalLanguageQueryCreate } from 'products/logs/frontend/generated/api'
import type { LogsNaturalLanguageQueryResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { logsNaturalLanguageSearchLogic } from './logsNaturalLanguageSearchLogic'

jest.mock('lib/api')
jest.mock('products/logs/frontend/generated/api')

const confidentResponse: LogsNaturalLanguageQueryResponseApi = {
    candidates: [
        {
            label: 'Errors in the last 2 hours',
            query: { dateRange: { date_from: '-2h' }, severityLevels: ['error'], serviceNames: [], filterGroup: [] },
            probability: 0.9,
        },
    ],
    confidence: 0.9,
    ranked_by: 'decision_model',
    dropped_count: 0,
}

describe('logsNaturalLanguageSearchLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    it('ignores a response that arrives after the dropdown closed and reopened', async () => {
        let resolveRequest: (response: LogsNaturalLanguageQueryResponseApi) => void = () => {}
        ;(logsNaturalLanguageQueryCreate as jest.Mock).mockReturnValueOnce(
            new Promise((resolve) => {
                resolveRequest = resolve
            })
        )
        const filtersLogic = logsViewerFiltersLogic({ id: 'test' })
        filtersLogic.mount()
        const filtersBefore = filtersLogic.values.filters

        const closedLogic = logsNaturalLanguageSearchLogic({ id: 'test' })
        const unmountClosed = closedLogic.mount()
        closedLogic.actions.askAi('error logs in the last 2 hours')
        unmountClosed()

        const reopenedLogic = logsNaturalLanguageSearchLogic({ id: 'test' })
        reopenedLogic.mount()
        resolveRequest(confidentResponse)
        await expectLogic(reopenedLogic).toFinishAllListeners()

        expect(reopenedLogic.values).toMatchObject({ response: null, appliedCount: 0 })
        expect(filtersLogic.values.filters).toEqual(filtersBefore)
    })
})
