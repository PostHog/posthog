import { ApiError } from 'lib/api'

import { evaluationErrorMessage } from './apiErrors'

describe('evaluationErrorMessage', () => {
    it('extracts a DRF field-level validation error', () => {
        const error = new ApiError('Non-OK response', 400, undefined, {
            enabled: ['Trial evaluation limit reached. Add a provider API key to re-enable.'],
        })
        expect(evaluationErrorMessage(error, 'fallback')).toBe(
            'Trial evaluation limit reached. Add a provider API key to re-enable.'
        )
    })

    it('extracts a nested field error from a model_configuration-style payload', () => {
        const error = new ApiError('Non-OK response', 400, undefined, {
            model_configuration: { provider_key_id: 'Provider key not found' },
        })
        expect(evaluationErrorMessage(error, 'fallback')).toBe('Provider key not found')
    })

    it('falls back to detail when no field errors are present', () => {
        const error = new ApiError('Something', 403, undefined, { detail: 'You do not have access' })
        expect(evaluationErrorMessage(error, 'fallback')).toBe('You do not have access')
    })

    it('falls back to the supplied default when nothing useful is available', () => {
        const error = new ApiError('Non-OK response [PATCH /api/...]', 500, undefined, null)
        expect(evaluationErrorMessage(error, 'fallback copy')).toBe('fallback copy')
    })

    it('unwraps a plain Error', () => {
        expect(evaluationErrorMessage(new Error('Network down'), 'fallback')).toBe('Network down')
    })
})
