import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { LogMessage } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { logsViewerDataLogic } from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'
import { logsSessionErrorsLogic } from 'products/logs/frontend/components/LogsViewer/logsSessionErrorsLogic'

const VIEWER_ID = 'test-viewer'

function makeLog(uuid: string, sessionId: string | null): LogMessage {
    return {
        uuid,
        trace_id: '',
        span_id: '',
        body: 'something happened',
        attributes: sessionId ? { sessionId } : {},
        timestamp: '2026-09-03T12:00:00.000Z',
        observed_timestamp: '2026-09-03T12:00:00.000Z',
        severity_text: 'info',
        severity_number: 9,
        level: 'info',
        resource_attributes: {},
        instrumentation_scope: '',
        event_name: '',
    }
}

describe('logsSessionErrorsLogic', () => {
    let logic: ReturnType<typeof logsSessionErrorsLogic.build>
    let dataLogic: ReturnType<typeof logsViewerDataLogic.build>
    let queryBodies: any[]

    const mountAll = (): void => {
        dataLogic = logsViewerDataLogic({ id: VIEWER_ID, autoLoad: false })
        dataLogic.mount()
        logic = logsSessionErrorsLogic({ id: VIEWER_ID })
        logic.mount()
    }

    beforeEach(() => {
        queryBodies = []
        useMocks({
            post: {
                '/api/environments/:team_id/logs/query/': () => [200, { results: [], maxExportableLogs: 5000 }],
                '/api/environments/:team_id/logs/sparkline/': () => [200, []],
                '/api/environments/:team_id/query/HogQLQuery': async ({ request }) => {
                    queryBodies.push(await request.json())
                    return [200, { results: [['session-a', 3]] }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.LOGS_SESSION_ERROR_BADGES]: true })
    })

    afterEach(() => {
        logic?.unmount()
        dataLogic?.unmount()
    })

    it('records a zero for every session it looked up, so the next page only asks about new ones', async () => {
        mountAll()
        dataLogic.actions.setLogs([makeLog('log-1', 'session-a'), makeLog('log-2', 'session-b')])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sessionErrorCounts).toEqual({ 'session-a': 3, 'session-b': 0 })
        expect(logic.values.unresolvedSessionIds).toEqual([])

        // A next page that adds one session must not re-ask about the two already answered.
        dataLogic.actions.setLogs([
            makeLog('log-1', 'session-a'),
            makeLog('log-2', 'session-b'),
            makeLog('log-3', 'session-c'),
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(queryBodies).toHaveLength(2)
        expect(queryBodies[1].query.query).toContain("'session-c'")
        expect(queryBodies[1].query.query).not.toContain("'session-a'")
    })

    it('deduplicates the sessions on the page', async () => {
        mountAll()
        dataLogic.actions.setLogs([
            makeLog('log-1', 'session-a'),
            makeLog('log-2', 'session-a'),
            makeLog('log-3', null),
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sessionIdsInView).toEqual(['session-a'])
        expect(queryBodies[0].query.query.match(/'session-a'/g)).toHaveLength(1)
    })

    it('queries nothing while the feature flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        mountAll()
        dataLogic.actions.setLogs([makeLog('log-1', 'session-a')])
        await expectLogic(logic).toFinishAllListeners()

        expect(queryBodies).toHaveLength(0)
        expect(logic.values.sessionErrorCounts).toEqual({})
    })

    it('drops counts from the previous filters when a fresh query lands', async () => {
        mountAll()
        dataLogic.actions.setLogs([makeLog('log-1', 'session-a')])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.sessionErrorCounts).toEqual({ 'session-a': 3 })

        dataLogic.actions.fetchLogs()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sessionErrorCounts).toEqual({})
    })
})
