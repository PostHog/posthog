import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType } from '~/types'

import { TraceErrorsLogicProps, traceErrorsLogic } from './traceErrorsLogic'

const TRACE_ID = '4BF92F3577B34DA6A3CE929D0E0E4736'
const SPAN_ID = '00F067AA0BA902B7'
const ALL_IDS: TraceErrorsLogicProps = {
    traceId: TRACE_ID,
    spanId: SPAN_ID,
    timestamp: '2026-06-02T08:00:00Z',
    sessionId: 'session-a',
    initialScope: null,
}

describe('traceErrorsLogic', () => {
    let logic: ReturnType<typeof traceErrorsLogic.build>
    let querySpy: jest.SpyInstance

    const mount = async (props: Partial<TraceErrorsLogicProps> = {}): Promise<void> => {
        logic = traceErrorsLogic({ ...ALL_IDS, ...props })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    const lastQuery = (): any => querySpy.mock.calls[querySpy.mock.calls.length - 1][0]

    const filterKeys = (): { key: string; value: unknown }[] =>
        lastQuery().filterGroup.values[0].values.map((filter: any) => ({ key: filter.key, value: filter.value }))

    beforeEach(() => {
        initKeaTests()
        querySpy = jest.spyOn(api, 'query').mockResolvedValue({ results: [] } as any)
    })

    afterEach(() => {
        logic?.unmount()
        querySpy.mockRestore()
    })

    // Getting the order wrong downgrades every trace that carries exact ids back to the session
    // guess, which is the behavior this surface replaced.
    it.each([
        ['every id', {}, ['span', 'trace', 'session']],
        ['no span id', { spanId: null }, ['trace', 'session']],
        ['no session', { sessionId: null }, ['span', 'trace']],
        ['a session only', { traceId: '', spanId: null }, ['session']],
        // An all-zero id is OpenTelemetry's "no id" sentinel, so it offers no exact scope.
        ['all-zero ids', { traceId: '0'.repeat(32), spanId: '0'.repeat(16) }, ['session']],
        ['nothing to match on', { traceId: '', spanId: null, sessionId: null }, []],
    ])('offers the scopes for a trace with %s, most precise first', async (_name, props, expected) => {
        await mount(props)

        expect(logic.values.availableScopes).toEqual(expected)
        expect(logic.values.effectiveScope).toBe(expected[0] ?? null)
    })

    // A trace-tier badge exists only when the span scope found nothing, so defaulting to the most
    // precise scope landed the click on the one list it had already ruled out.
    it.each([
        ['trace', 'trace'],
        ['session', 'session'],
    ])('opens on the %s scope the caller named, not the most precise one', async (_name, scope) => {
        await mount({ initialScope: scope as any })

        expect(logic.values.effectiveScope).toBe(scope)
    })

    // A scope the trace cannot offer must not strand the tab on an empty selection.
    it('ignores a named scope the trace does not offer', async () => {
        await mount({ initialScope: 'session', sessionId: null })

        expect(logic.values.effectiveScope).toBe('span')
    })

    // The control is the user speaking; the caller's scope was only a starting point.
    it('lets the scope control override the scope the caller named', async () => {
        await mount({ initialScope: 'trace' })
        logic.actions.setScope('session')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.effectiveScope).toBe('session')
    })

    // The filter decides which issues the tab lists, so a scope that sends the wrong property
    // lists another request's errors under this one.
    it.each([
        [
            'span',
            [
                { key: '$trace_id', value: TRACE_ID.toLowerCase() },
                { key: '$span_id', value: SPAN_ID.toLowerCase() },
            ],
        ],
        ['trace', [{ key: '$trace_id', value: TRACE_ID.toLowerCase() }]],
        ['session', [{ key: '$session_id', value: 'session-a' }]],
    ])('matches on the %s scope', async (scope, expected) => {
        await mount()
        logic.actions.setScope(scope as any)
        await expectLogic(logic).toFinishAllListeners()

        expect(filterKeys()).toEqual(expected)
        expect(lastQuery().filterGroup.values[0].values[0].type).toBe(PropertyFilterType.Event)
    })

    // An exception carrying a trace id happened inside that trace, so the exact scopes have no
    // reason to scan the six hours the session guess needs.
    it.each([
        ['trace', 'trace', '2026-06-02T07:00:00.000Z', '2026-06-02T09:00:00.000Z'],
        ['session', 'session', '2026-06-02T02:00:00.000Z', '2026-06-02T14:00:00.000Z'],
    ])('asks the %s scope over its own window', async (_name, scope, date_from, date_to) => {
        await mount()
        logic.actions.setScope(scope as any)
        await expectLogic(logic).toFinishAllListeners()

        expect(lastQuery().dateRange).toEqual({ date_from, date_to })
    })

    it('asks nothing when the trace offers no scope', async () => {
        await mount({ traceId: '', spanId: null, sessionId: null })

        expect(querySpy).not.toHaveBeenCalled()
    })
})
