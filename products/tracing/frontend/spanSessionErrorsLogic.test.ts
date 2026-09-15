import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeSpan } from './__mocks__/span'
import { spanSessionErrorsLogic } from './spanSessionErrorsLogic'
import { tracingDataLogic } from './tracingDataLogic'
import type { Span } from './types'

function spanWithSession(uuid: string, sessionId: string | null): Span {
    return makeSpan({ uuid, span_id: uuid, attributes: sessionId ? { sessionId } : {} })
}

describe('spanSessionErrorsLogic', () => {
    let logic: ReturnType<typeof spanSessionErrorsLogic.build>
    let dataLogic: ReturnType<typeof tracingDataLogic.build>
    let queryHogQLSpy: jest.SpyInstance

    // The loader success actions are what the list's fetches dispatch, so driving them is the
    // cheapest way to load a page without standing up the spans endpoint.
    const loadFirstPage = async (spans: Span[]): Promise<void> => {
        dataLogic.actions.fetchSpansSuccess(spans)
        await expectLogic(logic).toFinishAllListeners()
    }

    // A next page arrives as the whole accumulated list, the way the spans loader appends it.
    const loadNextPage = async (spans: Span[]): Promise<void> => {
        dataLogic.actions.fetchNextPageSuccess(spans)
        await expectLogic(logic).toFinishAllListeners()
    }

    const queriesRun = (): string[] => queryHogQLSpy.mock.calls.map((call) => call[0] as string)

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:teamId/tracing_config/': () => [
                    200,
                    {
                        tracing_distinct_id_attribute_keys: ['posthogDistinctId'],
                        tracing_session_id_attribute_keys: ['sessionId'],
                    },
                ],
            },
        })
        initKeaTests()
        queryHogQLSpy = jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [['session-a', 3]] } as any)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES], {
            [FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES]: true,
        })
        dataLogic = tracingDataLogic()
        dataLogic.mount()
        logic = spanSessionErrorsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        dataLogic.unmount()
        queryHogQLSpy.mockRestore()
    })

    it('records a zero for every session it looked up, so the next page only asks about new ones', async () => {
        await loadFirstPage([spanWithSession('span-1', 'session-a'), spanWithSession('span-2', 'session-b')])

        expect(logic.values.sessionErrorCounts).toEqual({ 'session-a': 3, 'session-b': 0 })
        // The row a badge sits on has to read its own session's count, and a clean session must
        // leave the row out rather than badge it with a zero.
        expect(logic.values.errorCountByRow.get('span-1')).toBe(3)
        expect(logic.values.errorCountByRow.has('span-2')).toBe(false)

        await loadNextPage([
            spanWithSession('span-1', 'session-a'),
            spanWithSession('span-2', 'session-b'),
            spanWithSession('span-3', 'session-c'),
        ])

        expect(queriesRun()).toHaveLength(2)
        expect(queriesRun()[1]).toContain("'session-c'")
        expect(queriesRun()[1]).not.toContain("'session-a'")
    })

    it('deduplicates the sessions on the page', async () => {
        await loadFirstPage([
            spanWithSession('span-1', 'session-a'),
            spanWithSession('span-2', 'session-a'),
            spanWithSession('span-3', null),
        ])

        expect(logic.values.sessionIdsInView).toEqual(['session-a'])
        expect(queriesRun()[0].match(/'session-a'/g)).toHaveLength(1)
    })

    it('asks only about exceptions that error tracking linked to an issue', async () => {
        await loadFirstPage([spanWithSession('span-1', 'session-a')])

        expect(queriesRun()[0]).toContain('isNotNull(properties.$exception_issue_id)')
    })

    it('queries nothing and scans no rows while the feature flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        await loadFirstPage([spanWithSession('span-1', 'session-a')])

        expect(queriesRun()).toHaveLength(0)
        expect(logic.values.sessionErrorCounts).toEqual({})
        // Empty because the resolve is skipped, not because the rows carry no session. Without
        // that guard every team pays the per-row attribute scan for a feature they cannot see.
        expect(logic.values.sessionIdsInView).toEqual([])
    })

    // The cap bounds one query's IN list. Capping the page's sessions instead would mean a list
    // that has already seen that many sessions never asks about the ones a new page brings.
    it('keeps asking about new sessions once the lookup cap is reached', async () => {
        const firstPage = Array.from({ length: 250 }, (_, i) => spanWithSession(`span-${i}`, `session-${i}`))
        await loadFirstPage(firstPage)

        expect(queriesRun()[0].match(/'session-\d+'/g)).toHaveLength(200)

        await loadNextPage([...firstPage, spanWithSession('span-new', 'session-new')])

        expect(queriesRun()[1]).toContain("'session-new'")
    })

    it('drops counts from the previous filters when a fresh query lands', async () => {
        await loadFirstPage([spanWithSession('span-1', 'session-a')])
        expect(logic.values.sessionErrorCounts).toEqual({ 'session-a': 3 })

        await loadFirstPage([])

        expect(logic.values.sessionErrorCounts).toEqual({})
    })

    // A first page shorter than the viewport asks for the next one immediately, which supersedes
    // the fresh page's lookup before its debounce elapses. The counts still have to go, or the
    // previous filters keep badging rows.
    it('drops the previous counts even when the next page supersedes the lookup', async () => {
        await loadFirstPage([spanWithSession('span-1', 'session-a')])
        expect(logic.values.sessionErrorCounts).toEqual({ 'session-a': 3 })

        // The fresh filters return no exceptions, so anything left over comes from the old page.
        queryHogQLSpy.mockResolvedValue({ results: [] } as any)

        const freshPage = [spanWithSession('span-2', 'session-b')]
        dataLogic.actions.fetchSpansSuccess(freshPage)
        dataLogic.actions.fetchNextPageSuccess(freshPage)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sessionErrorCounts).not.toHaveProperty('session-a')
    })
})
