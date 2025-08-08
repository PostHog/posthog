import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmObservabilityTraceLogic } from './llmObservabilityTraceLogic'

describe('llmObservabilityTraceLogic', () => {
    let logic: ReturnType<typeof llmObservabilityTraceLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/query/': { results: [] },
            },
        })
        initKeaTests()
        logic = llmObservabilityTraceLogic()
        logic.mount()
    })

    it('properly loads trace scene when trace ID contains a colon', async () => {
        const traceIdWithColon = 'session-summary:group:16-16:81008d53ff0a708b:da6c0390-409f-485c-aab3-5e910bcf8b33'
        const traceUrl = combineUrl(urls.llmObservabilityTrace(traceIdWithColon))
        const finalUrl = addProjectIdIfMissing(traceUrl.url, MOCK_TEAM_ID)

        router.actions.push(finalUrl)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.traceId).toBe(traceIdWithColon)
    })

    it('properly loads trace scene when trace ID contains multiple colons', async () => {
        const traceIdWithMultipleColons = 'namespace:trace:12345:abcdef:xyz'
        const traceUrl = combineUrl(urls.llmObservabilityTrace(traceIdWithMultipleColons))

        router.actions.push(addProjectIdIfMissing(traceUrl.url, MOCK_TEAM_ID))
        await expectLogic(logic).toMatchValues({
            traceId: traceIdWithMultipleColons,
        })
    })

    it('handles trace ID with event and timestamp parameters', async () => {
        const traceIdWithColon = 'session-summary:group:16-16:81008d53ff0a708b:da6c0390-409f-485c-aab3-5e910bcf8b33'
        const eventId = 'event123'
        const timestamp = '2024-01-01T00:00:00Z'
        const traceUrl = combineUrl(urls.llmObservabilityTrace(traceIdWithColon, { event: eventId, timestamp }))

        router.actions.push(addProjectIdIfMissing(traceUrl.url, MOCK_TEAM_ID))
        await expectLogic(logic).toMatchValues({
            traceId: traceIdWithColon,
            eventId: eventId,
            dateFrom: timestamp,
        })
    })
})
