import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { LogMessage } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { logsViewerDataLogic } from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'
import { logsSessionErrorsLogic } from 'products/logs/frontend/components/LogsViewer/logsSessionErrorsLogic'

const VIEWER_ID = 'test-viewer'

// Only uuid, attributes and timestamp are read; the rest satisfies the schema.
const BASE_LOG: LogMessage = {
    uuid: '',
    trace_id: '',
    span_id: '',
    body: 'something happened',
    attributes: {},
    timestamp: '2026-09-03T12:00:00.000Z',
    observed_timestamp: '2026-09-03T12:00:00.000Z',
    severity_text: 'info',
    severity_number: 9,
    level: 'info',
    resource_attributes: {},
    instrumentation_scope: '',
    event_name: '',
}

function makeLog(uuid: string, sessionId: string | null): LogMessage {
    return { ...BASE_LOG, uuid, attributes: sessionId ? { sessionId } : {} }
}

describe('logsSessionErrorsLogic', () => {
    let logic: ReturnType<typeof logsSessionErrorsLogic.build>
    let dataLogic: ReturnType<typeof logsViewerDataLogic.build>
    let queryBodies: any[]
    let pageResults: LogMessage[]

    // Loads a page the way the viewer does, through a landing logs query. That path carries the
    // short debounce; going through setLogs instead would pay the live-tail one in every test.
    const loadPage = async (logs: LogMessage[]): Promise<void> => {
        pageResults = logs
        dataLogic.actions.fetchLogs()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        queryBodies = []
        pageResults = []
        useMocks({
            post: {
                '/api/environments/:team_id/logs/query/': () => [
                    200,
                    { results: pageResults, maxExportableLogs: 5000 },
                ],
                '/api/environments/:team_id/query/HogQLQuery': async ({ request }) => {
                    queryBodies.push(await request.json())
                    return [200, { results: [['session-a', 3]] }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.LOGS_SESSION_ERROR_BADGES]: true })
        dataLogic = logsViewerDataLogic({ id: VIEWER_ID, autoLoad: false })
        dataLogic.mount()
        logic = logsSessionErrorsLogic({ id: VIEWER_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        dataLogic.unmount()
    })

    it('records a zero for every session it looked up, so the next page only asks about new ones', async () => {
        await loadPage([makeLog('log-1', 'session-a'), makeLog('log-2', 'session-b')])

        expect(logic.values.sessionErrorCounts).toEqual({ 'session-a': 3, 'session-b': 0 })

        // A live-tail poll that adds one session must not re-ask about the two already answered.
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
        await loadPage([makeLog('log-1', 'session-a'), makeLog('log-2', 'session-a'), makeLog('log-3', null)])

        expect(logic.values.sessionIdsInView).toEqual(['session-a'])
        expect(queryBodies[0].query.query.match(/'session-a'/g)).toHaveLength(1)
    })

    it('still builds a window when timestamps arrive as epoch numbers', async () => {
        await loadPage([
            { ...BASE_LOG, uuid: 'log-1', attributes: { sessionId: 'session-a' }, timestamp: '1788474031592' },
        ])

        expect(logic.values.sessionErrorCounts).toEqual({ 'session-a': 3 })
        expect(queryBodies[0].query.query).toContain('2026-')
    })

    it('queries nothing while the feature flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        await loadPage([makeLog('log-1', 'session-a')])

        expect(queryBodies).toHaveLength(0)
        expect(logic.values.sessionErrorCounts).toEqual({})
    })

    it('drops counts from the previous filters when a fresh query lands', async () => {
        await loadPage([makeLog('log-1', 'session-a')])
        expect(logic.values.sessionErrorCounts).toEqual({ 'session-a': 3 })

        await loadPage([])

        expect(logic.values.sessionErrorCounts).toEqual({})
    })
})
