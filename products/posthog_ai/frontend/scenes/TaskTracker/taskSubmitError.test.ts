import { ApiError } from 'lib/api'

import { describeTaskSubmitError } from './taskSubmitError'

describe('describeTaskSubmitError', () => {
    it('surfaces the backend error string instead of a generic message', () => {
        const error = new ApiError('boom', 400, undefined, { error: 'Repository is not connected.' })
        expect(describeTaskSubmitError(error, 'create').message).toBe('Repository is not connected.')
    })

    it.each([
        ['posthog_code_billing_limit_exceeded', 'Manage billing'],
        ['organization_deactivated', 'Manage billing'],
        ['usage_limit_exceeded', 'Manage billing'],
        ['code_access_required', 'Learn more'],
    ])('routes the %s refusal to a next-step button', (code, expectedLabel) => {
        const error = new ApiError('denied', 429, undefined, { code, error: 'You reached a limit.' })
        const { message, button } = describeTaskSubmitError(error, 'run')
        expect(message).toBe('You reached a limit.')
        expect(button?.label).toBe(expectedLabel)
    })

    it('has no button for an unclassified API error', () => {
        const error = new ApiError('boom', 500, undefined, { error: 'Something broke.' })
        expect(describeTaskSubmitError(error, 'run').button).toBeUndefined()
    })

    it('falls back to a step-specific message when the failure is not an ApiError', () => {
        expect(describeTaskSubmitError(new Error(''), 'create').message).toBe(
            'Could not create the task. Please try again.'
        )
        expect(describeTaskSubmitError(new Error(''), 'run').message).toBe('Could not start the run. Please try again.')
    })
})
