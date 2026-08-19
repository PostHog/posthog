import { ApiError } from 'lib/api'

import { describeTaskSubmitError } from './taskSubmitError'

describe('describeTaskSubmitError', () => {
    it('names the step and appends the backend reason for a generic failure', () => {
        const error = new ApiError('boom', 400, undefined, { error: 'Repository is not connected.' })
        expect(describeTaskSubmitError(error, 'create').message).toBe(
            'Could not create the task: Repository is not connected.'
        )
    })

    it('falls back to a friendly step message for an empty-body server error', () => {
        // fromResponse leaves no body message, so ApiError.message is the synthetic default; the toast
        // must not leak "API request failed with status: 503".
        const error = new ApiError(undefined, 503)
        expect(describeTaskSubmitError(error, 'run').message).toBe('Could not start the run. Please try again.')
    })

    it.each([
        ['posthog_code_billing_limit_exceeded', 'Manage billing'],
        ['usage_limit_exceeded', 'Manage billing'],
        // A deactivated org can't be fixed via billing — the backend copy says to contact support.
        ['organization_deactivated', 'Contact support'],
        ['code_access_required', 'Learn more'],
    ])('routes the %s refusal to a next-step button with the backend reason', (code, expectedLabel) => {
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
        expect(describeTaskSubmitError('nope', 'create').message).toBe('Could not create the task. Please try again.')
        expect(describeTaskSubmitError('nope', 'run').message).toBe('Could not start the run. Please try again.')
    })
})
