import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { tracingSpansSessionErrorCountsCreate } from 'products/tracing/frontend/generated/api'

import { makeSpan } from './__mocks__/span'
import { spanSessionErrorsLogic } from './spanSessionErrorsLogic'
import { tracingCorrelationConfigLogic } from './tracingCorrelationConfigLogic'
import { tracingDataLogic } from './tracingDataLogic'
import type { Span } from './types'

jest.mock('products/tracing/frontend/generated/api', () => ({
    tracingSpansSessionErrorCountsCreate: jest.fn(),
}))

const mockCountsCreate = tracingSpansSessionErrorCountsCreate as jest.MockedFunction<
    typeof tracingSpansSessionErrorCountsCreate
>

function spanWithSession(uuid: string, sessionId: string | null): Span {
    return makeSpan({ uuid, span_id: uuid, attributes: sessionId ? { sessionId } : {} })
}

describe('spanSessionErrorsLogic', () => {
    let logic: ReturnType<typeof spanSessionErrorsLogic.build>
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

    // The session ids each request asked about, in request order.
    const sessionsAsked = (): string[][] => mockCountsCreate.mock.calls.map(([, body]) => body.sessionIds)

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
        logic = spanSessionErrorsLogic()
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
        mockCountsCreate.mockResolvedValue({ results: [{ session_id: 'session-a', exceptions: 3 }] })
        setErrorTrackingAccess(AccessControlLevel.Viewer)
        mountLogics()
    })

    afterEach(() => {
        logic.unmount()
        dataLogic.unmount()
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

        expect(sessionsAsked()).toEqual([['session-a', 'session-b'], ['session-c']])
    })

    it('deduplicates the sessions on the page', async () => {
        await loadFirstPage([
            spanWithSession('span-1', 'session-a'),
            spanWithSession('span-2', 'session-a'),
            spanWithSession('span-3', null),
        ])

        expect(logic.values.sessionIdsInView).toEqual(['session-a'])
        expect(sessionsAsked()).toEqual([['session-a']])
    })

    it('asks over the window around the rows in view', async () => {
        await loadFirstPage([
            makeSpan({
                uuid: 'span-1',
                span_id: 'span-1',
                timestamp: '2026-06-02T08:00:00Z',
                attributes: { sessionId: 'a' },
            }),
        ])

        expect(mockCountsCreate.mock.calls[0][1]).toMatchObject({
            dateFrom: '2026-06-02T02:00:00.000Z',
            dateTo: '2026-06-02T14:00:00.000Z',
        })
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
        await loadFirstPage([spanWithSession('span-1', 'session-a')])

        expect(sessionsAsked()).toHaveLength(0)
        expect(logic.values.sessionErrorCounts).toEqual({})
        // Empty because the resolve is skipped, not because the rows carry no session. Without
        // that guard every team pays the per-row attribute scan for a feature they cannot see.
        expect(logic.values.sessionIdsInView).toEqual([])
    })

    // The cap bounds one request, not how many sessions a page can badge.
    it('splits a page over the cap into several requests and answers every session', async () => {
        const firstPage = Array.from({ length: 250 }, (_, i) => spanWithSession(`span-${i}`, `session-${i}`))
        await loadFirstPage(firstPage)

        expect(sessionsAsked().map((chunk) => chunk.length)).toEqual([200, 50])
        expect(Object.keys(logic.values.sessionErrorCounts)).toHaveLength(250)

        await loadNextPage([...firstPage, spanWithSession('span-new', 'session-new')])

        expect(sessionsAsked()[2]).toEqual(['session-new'])
    })

    // A team that stores the session under its own key resolves nothing until the configured keys
    // arrive, and that can happen after the first page has already been looked up.
    it('asks again when the configured session keys arrive after the page', async () => {
        await loadFirstPage([makeSpan({ uuid: 'span-1', span_id: 'span-1', attributes: { customSession: 'x' } })])
        expect(sessionsAsked()).toEqual([])

        tracingCorrelationConfigLogic.actions.loadTracingConfigSuccess({
            tracing_distinct_id_attribute_keys: ['posthogDistinctId'],
            tracing_session_id_attribute_keys: ['customSession'],
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(sessionsAsked()).toEqual([['x']])
    })

    // No usable timestamp means no window to ask over. The lookup has to stop there rather than
    // keep retrying a page it can never answer.
    it('asks nothing when no row in view has a usable timestamp', async () => {
        await loadFirstPage([
            makeSpan({ uuid: 'span-1', span_id: 'span-1', timestamp: 'not-a-date', attributes: { sessionId: 'a' } }),
        ])

        expect(sessionsAsked()).toEqual([])
        expect(logic.values.sessionErrorCounts).toEqual({})
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
        mockCountsCreate.mockResolvedValue({ results: [] })

        const freshPage = [spanWithSession('span-2', 'session-b')]
        dataLogic.actions.fetchSpansSuccess(freshPage)
        dataLogic.actions.fetchNextPageSuccess(freshPage)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sessionErrorCounts).not.toHaveProperty('session-a')
    })
})
