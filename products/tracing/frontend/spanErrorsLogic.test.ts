import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { tracingSpansErrorCountsCreate } from 'products/tracing/frontend/generated/api'

import { makeSpan } from './__mocks__/span'
import { spanErrorsLogic } from './spanErrorsLogic'
import { tracingCorrelationConfigLogic } from './tracingCorrelationConfigLogic'
import { tracingDataLogic } from './tracingDataLogic'
import type { Span } from './types'

jest.mock('products/tracing/frontend/generated/api', () => ({
    tracingSpansErrorCountsCreate: jest.fn(),
}))

const mockCountsCreate = tracingSpansErrorCountsCreate as jest.MockedFunction<typeof tracingSpansErrorCountsCreate>

const NO_COUNTS = { traceResults: [], spanResults: [], sessionResults: [] }

// A row with no trace or span id, so only the session join can answer it.
function spanWithSession(uuid: string, sessionId: string | null): Span {
    return makeSpan({
        uuid,
        trace_id: '',
        span_id: '',
        attributes: sessionId ? { sessionId } : {},
    })
}

function spanWithIds(uuid: string, traceId: string, spanId: string, sessionId?: string): Span {
    return makeSpan({
        uuid,
        trace_id: traceId,
        span_id: spanId,
        attributes: sessionId ? { sessionId } : {},
    })
}

describe('spanErrorsLogic', () => {
    let logic: ReturnType<typeof spanErrorsLogic.build>
    let dataLogic: ReturnType<typeof tracingDataLogic.build>

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

    const asked = (field: 'traceIds' | 'spanIds' | 'sessionIds'): string[][] =>
        mockCountsCreate.mock.calls.map(([, body]) => body[field]).filter((ids): ids is string[] => !!ids?.length)

    const setErrorTrackingAccess = (level: AccessControlLevel): void => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.ErrorTracking]: level,
            },
        } as AppContext
    }

    // The access level is read from the app context when the flag selector first runs, so a
    // test that changes it has to build the logics again afterwards.
    const mountLogics = (): void => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES], {
            [FEATURE_FLAGS.TRACING_SPAN_ERROR_BADGES]: true,
        })
        dataLogic = tracingDataLogic()
        dataLogic.mount()
        logic = spanErrorsLogic()
        logic.mount()
    }

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
        mockCountsCreate.mockReset()
        mockCountsCreate.mockResolvedValue({
            ...NO_COUNTS,
            sessionResults: [{ session_id: 'session-a', exceptions: 3 }],
        })
        setErrorTrackingAccess(AccessControlLevel.Viewer)
        mountLogics()
    })

    afterEach(() => {
        logic.unmount()
        dataLogic.unmount()
    })

    it('badges the most precise join each row has', async () => {
        mockCountsCreate.mockResolvedValue({
            traceResults: [{ trace_id: 'trace-a', exceptions: 4 }],
            spanResults: [{ span_id: 'span-thrower', exceptions: 1 }],
            sessionResults: [{ session_id: 'session-c', exceptions: 7 }],
        })

        await loadFirstPage([
            spanWithIds('row-span', 'trace-a', 'span-thrower'),
            spanWithIds('row-trace', 'trace-a', 'span-quiet'),
            spanWithSession('row-session', 'session-c'),
        ])

        expect(logic.values.errorBadgeByRow.get('row-span')).toEqual({ tier: 'span', count: 1 })
        expect(logic.values.errorBadgeByRow.get('row-trace')).toEqual({ tier: 'trace', count: 4 })
        expect(logic.values.errorBadgeByRow.get('row-session')).toEqual({ tier: 'session', count: 7 })
    })

    // An id of all zeros is OpenTelemetry's "no id" sentinel. Asking about it would match every
    // uninstrumented exception in the window to every uninstrumented row.
    it('treats an all-zero trace id as no trace at all', async () => {
        await loadFirstPage([spanWithIds('row-1', '0'.repeat(32), '0'.repeat(16), 'session-a')])

        expect(asked('traceIds')).toEqual([])
        expect(asked('sessionIds')).toEqual([['session-a']])
    })

    // The counts are not nested, so neither asking about the session only where the exact join
    // found nothing, nor suppressing a total that is not larger, is safe: both hide exceptions
    // from an SDK that stamps no trace id.
    const mockTraceAndSession = (trace: number, session: number): void => {
        mockCountsCreate.mockImplementation(async (_teamId, body) =>
            body.sessionIds?.length
                ? { ...NO_COUNTS, sessionResults: [{ session_id: 'session-a', exceptions: session }] }
                : { ...NO_COUNTS, traceResults: [{ trace_id: 'trace-a', exceptions: trace }] }
        )
    }

    it.each([
        ['the session holds more', 1, 3, { tier: 'trace', count: 1, alsoInSession: 3 }],
        ['the counts match', 2, 2, { tier: 'trace', count: 2, alsoInSession: 2 }],
        ['the session holds fewer', 3, 1, { tier: 'trace', count: 3, alsoInSession: 1 }],
        ['the session is clean', 2, 0, { tier: 'trace', count: 2 }],
    ])('carries the session total beside the trace count when %s', async (_name, trace, session, expected) => {
        mockTraceAndSession(trace, session)

        await loadFirstPage([spanWithIds('row-1', 'trace-a', 'span-1', 'session-a')])

        expect(asked('sessionIds')).toEqual([['session-a']])
        expect(logic.values.errorBadgeByRow.get('row-1')).toEqual(expected)
    })

    // The session tier is already the session count, so repeating it would read as two findings.
    it('does not repeat the session total on a session-tier badge', async () => {
        mockCountsCreate.mockResolvedValue({
            ...NO_COUNTS,
            sessionResults: [{ session_id: 'session-a', exceptions: 4 }],
        })

        await loadFirstPage([spanWithSession('row-1', 'session-a')])

        expect(logic.values.errorBadgeByRow.get('row-1')).toEqual({ tier: 'session', count: 4 })
    })

    // Span rows read their ids back as uppercase hex while the SDKs write them lowercase.
    it('asks about ids in the case the events are stored in', async () => {
        await loadFirstPage([spanWithIds('row-1', 'TRACE-A', 'SPAN-1')])

        expect(asked('traceIds')).toEqual([['trace-a']])
        expect(asked('spanIds')).toEqual([['span-1']])
    })

    it('records a zero for every id it looked up, so the next page only asks about new ones', async () => {
        await loadFirstPage([spanWithSession('span-1', 'session-a'), spanWithSession('span-2', 'session-b')])

        expect(logic.values.errorCounts.session).toEqual({ 'session-a': 3, 'session-b': 0 })
        // A clean session must leave the row out rather than badge it with a zero.
        expect(logic.values.errorBadgeByRow.get('span-1')).toEqual({ tier: 'session', count: 3 })
        expect(logic.values.errorBadgeByRow.has('span-2')).toBe(false)

        await loadNextPage([
            spanWithSession('span-1', 'session-a'),
            spanWithSession('span-2', 'session-b'),
            spanWithSession('span-3', 'session-c'),
        ])

        expect(asked('sessionIds')).toEqual([['session-a', 'session-b'], ['session-c']])
    })

    it('deduplicates the ids on the page', async () => {
        await loadFirstPage([
            spanWithSession('span-1', 'session-a'),
            spanWithSession('span-2', 'session-a'),
            spanWithSession('span-3', null),
        ])

        expect(asked('sessionIds')).toEqual([['session-a']])
    })

    // The exact join only has to cover the trace's own run, so it asks over a narrower range than
    // the session guess needs.
    it.each([
        ['trace', 'traceIds' as const, '2026-06-02T07:00:00.000Z', '2026-06-02T09:00:00.000Z'],
        ['session', 'sessionIds' as const, '2026-06-02T02:00:00.000Z', '2026-06-02T14:00:00.000Z'],
    ])('asks the %s join over its own window', async (_name, field, dateFrom, dateTo) => {
        const span =
            field === 'traceIds' ? spanWithIds('span-1', 'trace-a', 'span-1') : spanWithSession('span-1', 'session-a')

        await loadFirstPage([{ ...span, timestamp: '2026-06-02T08:00:00Z' }])

        const call = mockCountsCreate.mock.calls.find(([, body]) => body[field]?.length)
        expect(call?.[1]).toMatchObject({ dateFrom, dateTo })
    })

    // The endpoint refuses a person without Error Tracking access, so this gate is what keeps the
    // badges from showing an error state to them. It also spares every other team the scan.
    it.each([
        ['the feature flag is off', (): void => featureFlagLogic.actions.setFeatureFlags([], {})],
        [
            'the person has no Error Tracking access',
            (): void => {
                logic.unmount()
                dataLogic.unmount()
                setErrorTrackingAccess(AccessControlLevel.None)
                mountLogics()
            },
        ],
    ])('queries nothing and scans no rows while %s', async (_name, disable) => {
        disable()
        await loadFirstPage([spanWithIds('span-1', 'trace-a', 'span-1', 'session-a')])

        expect(mockCountsCreate).not.toHaveBeenCalled()
        expect(logic.values.errorCounts.session).toEqual({})
        // Empty because the resolve is skipped, not because the rows carry no session. Without
        // that guard every team pays the per-row attribute scan for a feature they cannot see.
        expect(logic.values.sessionIdByRow.size).toBe(0)
    })

    // The cap bounds one request, not how many rows a page can badge.
    it('splits a page over the cap into several requests and answers every id', async () => {
        const firstPage = Array.from({ length: 250 }, (_, i) => spanWithSession(`span-${i}`, `session-${i}`))
        await loadFirstPage(firstPage)

        expect(asked('sessionIds').map((chunk) => chunk.length)).toEqual([200, 50])
        expect(Object.keys(logic.values.errorCounts.session)).toHaveLength(250)

        await loadNextPage([...firstPage, spanWithSession('span-new', 'session-new')])

        expect(asked('sessionIds')[2]).toEqual(['session-new'])
    })

    // A team that stores the session under its own key resolves nothing until the configured keys
    // arrive, and that can happen after the first page has already been looked up.
    it('asks again when the configured session keys arrive after the page', async () => {
        await loadFirstPage([
            makeSpan({ uuid: 'span-1', trace_id: '', span_id: '', attributes: { customSession: 'x' } }),
        ])
        expect(asked('sessionIds')).toEqual([])

        tracingCorrelationConfigLogic.actions.loadTracingConfigSuccess({
            tracing_distinct_id_attribute_keys: ['posthogDistinctId'],
            tracing_session_id_attribute_keys: ['customSession'],
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(asked('sessionIds')).toEqual([['x']])
    })

    // No usable timestamp means no window to ask over. The lookup has to stop there rather than
    // keep retrying a page it can never answer.
    it('asks nothing when no row in view has a usable timestamp', async () => {
        await loadFirstPage([{ ...spanWithSession('span-1', 'session-a'), timestamp: 'not-a-date' }])

        expect(mockCountsCreate).not.toHaveBeenCalled()
        expect(logic.values.errorCounts.session).toEqual({})
    })

    it('drops counts from the previous filters when a fresh query lands', async () => {
        await loadFirstPage([spanWithSession('span-1', 'session-a')])
        expect(logic.values.errorCounts.session).toEqual({ 'session-a': 3 })

        await loadFirstPage([])

        expect(logic.values.errorCounts.session).toEqual({})
    })

    // A first page shorter than the viewport asks for the next one immediately, which supersedes
    // the fresh page's lookup before its debounce elapses. The counts still have to go, or the
    // previous filters keep badging rows.
    it('drops the previous counts even when the next page supersedes the lookup', async () => {
        await loadFirstPage([spanWithSession('span-1', 'session-a')])
        expect(logic.values.errorCounts.session).toEqual({ 'session-a': 3 })

        // The fresh filters return no exceptions, so anything left over comes from the old page.
        mockCountsCreate.mockResolvedValue(NO_COUNTS)

        const freshPage = [spanWithSession('span-2', 'session-b')]
        dataLogic.actions.fetchSpansSuccess(freshPage)
        dataLogic.actions.fetchNextPageSuccess(freshPage)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.errorCounts.session).not.toHaveProperty('session-a')
    })
})
