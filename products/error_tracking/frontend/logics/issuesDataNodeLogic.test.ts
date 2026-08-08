import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { ErrorTrackingQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { issuesDataNodeLogic } from './issuesDataNodeLogic'

const query: ErrorTrackingQuery = {
    kind: NodeKind.ErrorTrackingQuery,
    orderBy: 'last_seen',
    dateRange: {},
    volumeResolution: 0,
    filterGroup: { type: 'AND', values: [] } as any,
    withAggregations: true,
    withFirstEvent: false,
}

describe('issuesDataNodeLogic', () => {
    let logic: ReturnType<typeof issuesDataNodeLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/': { results: [] },
            },
        })
        initKeaTests()
        logic = issuesDataNodeLogic({ key: 'test', query })
        logic.mount()
    })

    afterEach(() => logic?.unmount())

    it('captures a failure event so a broken load is measurable', () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        captureSpy.mockClear()

        logic.actions.loadDataFailure('Server error', { status: 500, code: 'query_error' })

        const failureCalls = captureSpy.mock.calls.filter((call) => call[0] === 'error_tracking_issue_list_load_failed')
        expect(failureCalls).toHaveLength(1)
        expect(failureCalls[0][1]).toMatchObject({
            error_status: 500,
            error_code: 'query_error',
            was_cancelled: false,
        })
    })

    it('marks aborted loads as cancelled', () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        captureSpy.mockClear()

        logic.actions.loadDataFailure('Aborted', { name: 'AbortError' })

        const failureCalls = captureSpy.mock.calls.filter((call) => call[0] === 'error_tracking_issue_list_load_failed')
        expect(failureCalls).toHaveLength(1)
        expect(failureCalls[0][1]).toMatchObject({ was_cancelled: true })
    })
})
