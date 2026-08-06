import { describe, expect, it, vi } from 'vitest'

import { handleToolError, ToolInputValidationError } from '@/lib/errors'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))

describe('handleToolError with ToolInputValidationError', () => {
    it('returns the pre-formatted message verbatim without capturing an exception', () => {
        const error = new ToolInputValidationError('Invalid input for "action-get": missing required parameter: id')

        const result = handleToolError(error, 'action-get')

        expect(result.isError).toBe(true)
        const [content] = result.content as Array<{ type: string; text: string }>
        expect(content?.type).toBe('text')
        expect(content?.text).toBe(
            'Error: [action-get]: Invalid input for "action-get": missing required parameter: id'
        )
        expect(captureException).not.toHaveBeenCalled()
    })
})
