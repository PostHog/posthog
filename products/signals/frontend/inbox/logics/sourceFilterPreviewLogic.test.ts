import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    SourceFilterCatalogApi,
    SourceFilterPreviewResponseApi,
    SourceFilterValidateResponseApi,
} from 'products/signals/frontend/generated/api.schemas'

import { INBOX_EVENTS } from '../inboxAnalytics'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../types'
import { previewScopeIds, sourceFilterPreviewLogic } from './sourceFilterPreviewLogic'

const catalog: SourceFilterCatalogApi = {
    source_product: 'linear',
    source_type: 'issue',
    catalog_version: 2,
    filter_fields: [{ name: 'assignee_id', type: 'string', description: 'Assignee.' }],
    starter_expressions: ['assignee_id IS NULL'],
    preview_supported: true,
}

function sourceConfig(product: SignalSourceProduct, type: SignalSourceType): SignalSourceConfig {
    return {
        id: `config-${product}`,
        source_product: product,
        source_type: type,
        enabled: true,
        config: {},
        created_at: '2026-11-01T00:00:00Z',
        updated_at: '2026-11-01T00:00:00Z',
        status: null,
    }
}

const linearConfig = sourceConfig(SignalSourceProduct.Linear, SignalSourceType.Issue)

function okPreview(passingCount: number, lookbackDays = 7): SourceFilterPreviewResponseApi {
    return {
        status: 'ok',
        error: null,
        error_code: null,
        error_start: null,
        error_end: null,
        catalog_version: 2,
        lookback_days: lookbackDays,
        total_count: 10,
        passing_count: passingCount,
        excluded_count: 10 - passingCount,
        malformed_count: 0,
        passing: [],
        excluded: [],
    }
}

const INVALID: SourceFilterValidateResponseApi = {
    valid: false,
    catalog_version: 2,
    error: 'Unknown field projct.',
    error_code: 'unknown_field',
    error_start: 0,
    error_end: 6,
}

type MockResponse = [number, unknown] | Response
type Responder = (body: Record<string, any>) => MockResponse | Promise<MockResponse>

function throttled(retryAfter: string | null): Response {
    return HttpResponse.json(
        { detail: 'Request was throttled.' },
        { status: 429, headers: retryAfter ? { 'Retry-After': retryAfter } : {} }
    )
}

describe('sourceFilterPreviewLogic', () => {
    let logic: ReturnType<typeof sourceFilterPreviewLogic.build>
    let validateBodies: Record<string, any>[]
    let previewBodies: Record<string, any>[]
    let respondToValidate: Responder
    let respondToPreview: Responder

    beforeEach(() => {
        validateBodies = []
        previewBodies = []
        respondToValidate = ({ expression }) =>
            expression.includes('projct') ? [200, INVALID] : [200, { ...INVALID, valid: true, error: null }]
        respondToPreview = () => [200, okPreview(4)]
        useMocks({
            post: {
                '/api/projects/:team_id/signals/source_configs/filter_validate/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    validateBodies.push(body)
                    return respondToValidate(body)
                },
                '/api/projects/:team_id/signals/source_configs/filter_preview/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    previewBodies.push(body)
                    return respondToPreview(body)
                },
            },
        })
        initKeaTests()
        jest.useFakeTimers()
        logic = sourceFilterPreviewLogic({ sourceConfig: linearConfig, catalog })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    async function advance(ms: number): Promise<void> {
        await jest.advanceTimersByTimeAsync(ms)
        await expectLogic(logic).toFinishAllListeners()
    }

    test.each([
        ['saved allowlist', null, {}],
        ['every team', [], { scope_ids: [] }],
        ['picked teams', ['team-a'], { scope_ids: ['team-a'] }],
    ])('validates, then previews with the %s', async (_, scopeIds, scopeBody) => {
        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds })
        expect(logic.values.previewLoading).toBe(true)

        await advance(299)
        expect(validateBodies).toEqual([])

        await advance(1)
        expect(validateBodies).toEqual([
            { source_product: 'linear', source_type: 'issue', expression: 'assignee_id IS NULL' },
        ])
        expect(previewBodies).toEqual([])

        await advance(500)
        expect(previewBodies).toEqual([
            { source_product: 'linear', source_type: 'issue', expression: 'assignee_id IS NULL', ...scopeBody },
        ])
        expect(logic.values).toMatchObject({
            previewResult: okPreview(4),
            previewLoading: false,
            previewRequestError: null,
        })
    })

    it('previews a blank expression, and debounces a burst of edits into one request', async () => {
        logic.actions.setPreviewInput({ expression: 'assignee', scopeIds: null })
        await advance(200)
        logic.actions.setPreviewInput({ expression: '', scopeIds: null })
        await advance(800)

        expect(validateBodies.map((body) => body.expression)).toEqual([''])
        expect(previewBodies.map((body) => body.expression)).toEqual([''])
        expect(logic.values.previewResult).toEqual(okPreview(4))
    })

    it('never previews an invalid expression, and synthesizes an invalid result', async () => {
        respondToPreview = () => [200, okPreview(4, 14)]
        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds: null })
        await advance(800)
        expect(previewBodies).toHaveLength(1)

        logic.actions.setPreviewInput({ expression: "projct = 'Core'", scopeIds: null })
        await advance(2000)

        expect(previewBodies).toHaveLength(1)
        expect(logic.values.previewLoading).toBe(false)
        expect(logic.values.previewResult).toEqual({
            status: 'invalid_expression',
            error: 'Unknown field projct.',
            error_code: 'unknown_field',
            error_start: 0,
            error_end: 6,
            catalog_version: 2,
            lookback_days: 14,
            total_count: 0,
            passing_count: 0,
            excluded_count: 0,
            malformed_count: 0,
            passing: [],
            excluded: [],
        })
    })

    it('ignores a preview response for input that changed while it was in flight', async () => {
        let releaseFirst: () => void = () => {}
        respondToPreview = ({ expression }) =>
            expression === 'first'
                ? new Promise((resolve) => {
                      releaseFirst = () => resolve([200, okPreview(1)])
                  })
                : [200, okPreview(2)]

        logic.actions.setPreviewInput({ expression: 'first', scopeIds: null })
        await jest.advanceTimersByTimeAsync(800)
        expect(previewBodies.map((body) => body.expression)).toEqual(['first'])

        logic.actions.setPreviewInput({ expression: 'second', scopeIds: null })
        releaseFirst()
        await advance(0)
        expect(logic.values.previewResult).toBeNull()
        expect(logic.values.previewLoading).toBe(true)

        await advance(800)
        expect(logic.values.previewResult).toEqual(okPreview(2))
        expect(logic.values.previewLoading).toBe(false)
    })

    test.each([
        ['validate', 429, 'throttled'],
        ['validate', 500, 'failed'],
        ['preview', 429, 'throttled'],
        ['preview', 500, 'failed'],
        ['preview', 400, 'failed'],
    ] as const)('reports a %s %s as %s, and retryPreview recovers', async (endpoint, status, expected) => {
        const failing: Responder = () => [status, { detail: 'Nope.' }]
        const working = endpoint === 'validate' ? respondToValidate : respondToPreview
        if (endpoint === 'validate') {
            respondToValidate = failing
        } else {
            respondToPreview = failing
        }

        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds: null })
        await advance(800)
        expect(logic.values).toMatchObject({ previewRequestError: expected, previewLoading: false })

        if (endpoint === 'validate') {
            respondToValidate = working
        } else {
            respondToPreview = working
        }
        const requestsBefore = previewBodies.length
        logic.actions.retryPreview()
        await advance(0)

        expect(previewBodies).toHaveLength(requestsBefore + 1)
        expect(logic.values).toMatchObject({
            previewResult: okPreview(4),
            previewRequestError: null,
            previewLoading: false,
        })
    })

    test.each([
        ['the Retry-After header', '2', 2000],
        ['the fallback without a Retry-After header', null, 10_000],
    ])('retries a throttled preview once after %s', async (_, retryAfter, waitMs) => {
        let throttle = true
        respondToPreview = () => (throttle ? throttled(retryAfter) : [200, okPreview(4)])

        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds: null })
        await advance(800)
        expect(logic.values.previewRequestError).toBe('throttled')

        throttle = false
        await advance(waitMs - 1)
        expect(previewBodies).toHaveLength(1)

        await advance(1)
        expect(validateBodies).toHaveLength(2)
        expect(previewBodies).toHaveLength(2)
        expect(logic.values).toMatchObject({ previewResult: okPreview(4), previewRequestError: null })
    })

    it('replaces a pending throttled retry with a new input', async () => {
        respondToPreview = ({ expression }) => (expression === 'first' ? throttled('5') : [200, okPreview(2)])

        logic.actions.setPreviewInput({ expression: 'first', scopeIds: null })
        await advance(800)
        logic.actions.setPreviewInput({ expression: 'second', scopeIds: null })
        await advance(10_000)

        expect(previewBodies.map((body) => body.expression)).toEqual(['first', 'second'])
        expect(logic.values).toMatchObject({ previewResult: okPreview(2), previewRequestError: null })
    })

    it('retries at once when the tab shows again after the retry deadline passed', async () => {
        let throttle = true
        respondToPreview = () => (throttle ? throttled('60') : [200, okPreview(4)])

        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds: null })
        await advance(800)
        expect(logic.values.previewRequestError).toBe('throttled')

        const hiddenSpy = jest.spyOn(document, 'hidden', 'get').mockReturnValue(true)
        try {
            document.dispatchEvent(new Event('visibilitychange'))
            throttle = false
            await advance(120_000)
            expect(previewBodies).toHaveLength(1)

            hiddenSpy.mockReturnValue(false)
            document.dispatchEvent(new Event('visibilitychange'))
            await advance(0)
            expect(previewBodies).toHaveLength(2)
            expect(logic.values).toMatchObject({ previewResult: okPreview(4), previewRequestError: null })
        } finally {
            hiddenSpy.mockRestore()
            document.dispatchEvent(new Event('visibilitychange'))
        }
    })

    it('captures each shown result once, with counts and no expression', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const shown = (): unknown[] =>
            capture.mock.calls.filter(([event]) => event === INBOX_EVENTS.SOURCE_FILTER_PREVIEW_SHOWN).map(([, p]) => p)
        const base = { inbox_client: 'cloud', source_product: 'linear', source_type: 'issue' }

        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds: null })
        await advance(800)
        logic.actions.setPreviewInput({ expression: "projct = 'Core'", scopeIds: null })
        await advance(800)
        respondToValidate = () => [500, { detail: 'Nope.' }]
        logic.actions.setPreviewInput({ expression: 'priority = 1', scopeIds: null })
        await advance(800)

        expect(shown()).toEqual([
            {
                ...base,
                status: 'ok',
                request_error: null,
                total_count: 10,
                passing_count: 4,
                excluded_count: 6,
                malformed_count: 0,
            },
            { ...base, status: 'invalid_expression', request_error: null },
            { ...base, status: null, request_error: 'failed' },
        ])
        capture.mockRestore()
    })

    it('sends nothing for an input equal to the current one', async () => {
        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds: ['team-a', 'team-b'] })
        await advance(800)
        expect(previewBodies).toHaveLength(1)

        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds: ['team-a', 'team-b'] })
        expect(logic.values.previewLoading).toBe(false)
        await advance(2000)

        expect(validateBodies).toHaveLength(1)
        expect(previewBodies).toHaveLength(1)
    })

    it('drops a validation that lands after unmount', async () => {
        let release: () => void = () => {}
        respondToValidate = () =>
            new Promise((resolve) => {
                release = () => resolve([200, { ...INVALID, valid: true, error: null }])
            })
        logic.actions.setPreviewInput({ expression: 'assignee_id IS NULL', scopeIds: null })
        await jest.advanceTimersByTimeAsync(300)
        expect(validateBodies).toHaveLength(1)

        logic.unmount()
        release()
        await jest.advanceTimersByTimeAsync(2000)

        expect(previewBodies).toEqual([])
        logic.mount()
    })

    test.each([
        ['a source without teams', sourceConfig(SignalSourceProduct.Github, SignalSourceType.Issue), 'all', [], null],
        ['all Linear teams', linearConfig, 'all', ['team-a'], []],
        ['picked Linear teams', linearConfig, 'selected', ['team-a'], ['team-a']],
        ['a Linear selection with no teams yet', linearConfig, 'selected', [], null],
    ] as const)('previewScopeIds for %s', (_, config, teamScope, teamIds, expected) => {
        expect(previewScopeIds(config, { teamScope, teamIds: [...teamIds] })).toEqual(expected)
    })
})
