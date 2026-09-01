import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
    ExecCommandError,
    handleToolError,
    MissingProjectContextError,
    PostHogApiError,
    PostHogValidationError,
    type ToolErrorCode,
    ToolInputValidationError,
} from '@/lib/errors'
import { POSTHOG_META_KEY } from '@/tools/types'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))

function apiError(status: number): PostHogApiError {
    return new PostHogApiError({
        status,
        statusText: 'Error',
        body: 'body',
        url: 'https://us.posthog.com/api/projects/1/actions/9/',
        method: 'GET',
    })
}

describe('tool error codes', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it.each<{ name: string; error: unknown; code: ToolErrorCode }>([
        { name: 'no project selected', error: new MissingProjectContextError(), code: 'missing_project_context' },
        { name: 'input rejected by the schema', error: new ToolInputValidationError('bad'), code: 'invalid_input' },
        {
            name: 'exec rejection, which keeps its own reason',
            error: new ExecCommandError('nope', 'unknown_tool'),
            code: 'unknown_tool',
        },
        { name: 'a 404', error: apiError(404), code: 'not_found' },
        { name: 'a 429', error: apiError(429), code: 'rate_limited' },
        { name: 'an unclassified 4xx', error: apiError(409), code: 'invalid_request' },
        {
            name: 'a rejected field',
            error: new PostHogValidationError({
                detail: 'This field is required.',
                attr: 'name',
                code: 'required',
                extra: undefined,
                url: 'https://us.posthog.com/api/projects/1/actions/',
                method: 'POST',
            }),
            code: 'validation_error',
        },
        { name: 'a 500', error: apiError(500), code: 'upstream_error' },
        { name: 'an unexpected failure', error: new Error('boom'), code: 'internal_error' },
    ])('classifies $name as $code', ({ error, code }) => {
        const result = handleToolError(error, 'action-get')

        expect(result.isError).toBe(true)
        const [content] = result.content as Array<{ text: string }>
        expect(content?.text).toContain(`error_code: ${code}`)
        expect(result._meta?.[POSTHOG_META_KEY]).toEqual({ errorCode: code })
    })

    it('keeps the human-readable message ahead of the code', () => {
        const result = handleToolError(new ExecCommandError('Usage: search <pattern>', 'usage'), 'exec')

        const [content] = result.content as Array<{ text: string }>
        expect(content?.text).toBe('Error: [exec]: Usage: search <pattern>\n\nerror_code: usage')
    })
})
