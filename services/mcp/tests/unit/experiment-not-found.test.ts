import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import {
    findRecoverableApiError,
    handleToolError,
    PostHogApiError,
    PostHogPermissionError,
    PostHogRateLimitError,
    PostHogValidationError,
} from '@/lib/errors'
import { getResultsHandler } from '@/tools/experiments/getResults'
import type { Context } from '@/tools/types'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))
vi.mock('@/lib/posthog/analytics', () => ({
    AnalyticsEvent: { MCP_TOOL_CALL: '$mcp_tool_call' },
}))
vi.mock('@/lib/posthog/flags', () => ({
    isFeatureFlagEnabled: vi.fn().mockResolvedValue(false),
}))

// An agent passing a guessed or stale experiment id gets a 404. The client rewrites it
// into a message that names the recovery path, but that message must stay a typed 4xx:
// a bare Error skipped the recoverable branch of handleToolError, so every such miss was
// captured as an exception and counted as an internal failure with no message.
describe('experiment not-found rewrite', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    const stubNotFound = (): void => {
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Not found.' }), { status: 404 }))
        )
    }
    const buildClient = (): ApiClient => new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })

    it('returns a typed 404 that keeps the experiment-specific message', async () => {
        stubNotFound()

        const result = await buildClient().experiments({ projectId: '42' }).get({ experimentId: 999 })

        expect(result.success).toBe(false)
        if (result.success) {
            return
        }
        expect(result.error).toBeInstanceOf(PostHogApiError)
        expect((result.error as PostHogApiError).status).toBe(404)
        expect(result.error.message).toContain('Experiment 999 not found in this project')
        expect(result.error.message).toContain('experiment-list')
    })

    it('rewrites a lifecycle action 404 that carries only the generic detail, since that means the experiment is missing', async () => {
        stubNotFound()

        const result = await buildClient()
            .request({ method: 'POST', path: '/api/projects/42/experiments/999/launch/' })
            .then(
                () => undefined,
                (error: unknown) => error
            )

        expect(result).toBeInstanceOf(PostHogApiError)
        expect((result as PostHogApiError).status).toBe(404)
        expect((result as PostHogApiError).message).toContain('Experiment 999 not found in this project')
    })

    it('passes a sub-resource 404 through with the backend detail instead of claiming the experiment is missing', async () => {
        vi.stubGlobal(
            'fetch',
            vi
                .fn()
                .mockResolvedValue(
                    new Response(JSON.stringify({ detail: 'No completed recalculation found' }), { status: 404 })
                )
        )

        const result = await buildClient()
            .request({ method: 'GET', path: '/api/projects/42/experiments/29/metrics_recalculation/latest/' })
            .then(
                () => undefined,
                (error: unknown) => error
            )

        expect(result).toBeInstanceOf(PostHogApiError)
        expect((result as PostHogApiError).status).toBe(404)
        expect((result as PostHogApiError).message).toContain('No completed recalculation found')
        expect((result as PostHogApiError).message).not.toContain('Experiment 29 not found')
    })

    it('still rewrites the experiment resource 404 when the URL carries a query string', async () => {
        stubNotFound()

        const result = await buildClient()
            .request({ method: 'GET', path: '/api/projects/42/experiments/999/', query: { refresh: true } })
            .then(
                () => undefined,
                (error: unknown) => error
            )

        expect((result as PostHogApiError).message).toContain('Experiment 999 not found in this project')
    })

    it('keeps the plain path for 404s on other endpoints', async () => {
        stubNotFound()

        const result = await buildClient()
            .request({ method: 'GET', path: '/api/projects/42/feature_flags/999/' })
            .then(
                () => undefined,
                (error: unknown) => error
            )

        expect(result).toBeInstanceOf(PostHogApiError)
        expect((result as PostHogApiError).status).toBe(404)
        expect((result as PostHogApiError).message).not.toContain('Experiment')
    })

    it('is handled as agent-recoverable: the message is returned verbatim and no exception is captured', async () => {
        stubNotFound()

        const result = await buildClient().experiments({ projectId: '42' }).get({ experimentId: 999 })
        const handled = handleToolError(result.success ? undefined : result.error, 'experiment-get')

        expect(handled.isError).toBe(true)
        expect(handled.content[0]).toMatchObject({
            type: 'text',
            text: expect.stringContaining('Experiment 999 not found in this project'),
        })
        expect(captureException).not.toHaveBeenCalled()
    })

    it('stays reachable through the results tool, which wraps the failure with a cause', async () => {
        const notFound = new PostHogApiError({
            status: 404,
            statusText: 'Not Found',
            body: '{"detail":"Not found."}',
            url: 'https://us.posthog.com/api/projects/42/experiments/999/',
            method: 'GET',
            message: 'Experiment 999 not found in this project.',
        })
        const context = {
            api: {
                experiments: () => ({
                    getMetricResults: vi.fn().mockResolvedValue({ success: false, error: notFound }),
                }),
            },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
        } as unknown as Context

        const thrown = await getResultsHandler(context, { id: 999, refresh: false }).then(
            () => undefined,
            (error: unknown) => error
        )

        expect(thrown).toBeInstanceOf(Error)
        expect((thrown as Error).message).toContain('Experiment 999 not found in this project')
        expect(findRecoverableApiError(thrown)).toBe(notFound)
        expect(handleToolError(thrown, 'experiment-results-get').isError).toBe(true)
        expect(captureException).not.toHaveBeenCalled()
    })

    it('keeps other 4xx failures of the results tool captured, since they point at a query built here', async () => {
        const badQuery = new PostHogValidationError({
            detail: 'exposure_criteria contains unknown key(s): properties.',
            attr: 'exposure_criteria',
            code: 'invalid_input',
            extra: undefined,
            url: 'https://us.posthog.com/api/environments/42/query/',
            method: 'POST',
        })
        const context = {
            api: {
                experiments: () => ({
                    getMetricResults: vi.fn().mockResolvedValue({ success: false, error: badQuery }),
                }),
            },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
        } as unknown as Context

        const thrown = await getResultsHandler(context, { id: 999, refresh: false }).then(
            () => undefined,
            (error: unknown) => error
        )

        expect((thrown as Error).message).toContain('Failed to get experiment results')
        expect(findRecoverableApiError(thrown)).toBeUndefined()
        const handled = handleToolError(thrown, 'experiment-results-get')
        expect(handled.isError).toBe(true)
        expect(handled.content[0]).toMatchObject({ text: expect.stringContaining('unknown key(s): properties') })
        expect(captureException).toHaveBeenCalledTimes(1)
    })

    const resultsContextFailingWith = (error: Error): Context =>
        ({
            api: {
                experiments: () => ({
                    getMetricResults: vi.fn().mockResolvedValue({ success: false, error }),
                }),
            },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
        }) as unknown as Context

    const throwFromResults = (error: Error): Promise<unknown> =>
        getResultsHandler(resultsContextFailingWith(error), { id: 999, refresh: false }).then(
            () => undefined,
            (thrown: unknown) => thrown
        )

    it('keeps a rate limit on the results tool agent-recoverable instead of capturing it', async () => {
        const throttled = new PostHogRateLimitError({
            body: '{"detail":"Request was throttled."}',
            url: 'https://us.posthog.com/api/environments/42/query/',
            method: 'POST',
            retryAfterSeconds: 5,
        })

        const thrown = await throwFromResults(throttled)

        expect(findRecoverableApiError(thrown)).toBe(throttled)
        const handled = handleToolError(thrown, 'experiment-results-get')
        expect(handled.content[0]).toMatchObject({ text: expect.stringContaining('rate limit') })
        expect(captureException).not.toHaveBeenCalled()
    })

    it('keeps a permission denial on the results tool on the permission path with its guidance', async () => {
        const denied = new PostHogPermissionError({
            detail: 'You do not have access to this project.',
            url: 'https://us.posthog.com/api/environments/42/query/',
            method: 'POST',
        })

        const thrown = await throwFromResults(denied)

        const handled = handleToolError(thrown, 'experiment-results-get')
        expect(handled.content[0]).toMatchObject({ text: expect.stringContaining('do not have access') })
        expect(captureException).toHaveBeenCalledWith(
            expect.anything(),
            undefined,
            expect.objectContaining({ is_permission_error: true })
        )
    })

    it('still captures a 5xx from the results tool as an exception', async () => {
        const serverError = new PostHogApiError({
            status: 500,
            statusText: 'Internal Server Error',
            body: '{"detail":"query failed"}',
            url: 'https://us.posthog.com/api/environments/42/query/',
            method: 'POST',
        })

        const thrown = await throwFromResults(serverError)

        expect(handleToolError(thrown, 'experiment-results-get').isError).toBe(true)
        expect(captureException).toHaveBeenCalledTimes(1)
    })
})
