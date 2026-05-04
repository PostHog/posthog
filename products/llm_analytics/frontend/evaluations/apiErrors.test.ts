import { ApiError } from 'lib/api'

import { evaluationErrorMessage } from './apiErrors'

describe('evaluationErrorMessage', () => {
    it.each<[string, unknown, string]>([
        [
            'extracts a DRF field-level validation error',
            new ApiError('Non-OK response', 400, undefined, {
                enabled: ['Trial evaluation limit reached. Add a provider API key to re-enable.'],
            }),
            'Trial evaluation limit reached. Add a provider API key to re-enable.',
        ],
        [
            'extracts a nested field error from a model_configuration-style payload',
            new ApiError('Non-OK response', 400, undefined, {
                model_configuration: { provider_key_id: 'Provider key not found' },
            }),
            'Provider key not found',
        ],
        [
            'prefers detail over other keys on APIException payloads',
            new ApiError('Non-OK response', 400, undefined, {
                type: 'validation_error',
                code: 'invalid',
                detail: 'The request body is malformed.',
            }),
            'The request body is malformed.',
        ],
        [
            'returns detail when that is all the response carries',
            new ApiError('Something', 403, undefined, { detail: 'You do not have access' }),
            'You do not have access',
        ],
        [
            'falls back to the supplied default when nothing useful is available',
            new ApiError('Non-OK response [PATCH /api/...]', 500, undefined, null),
            'fallback copy',
        ],
        ['unwraps a plain Error', new Error('Network down'), 'Network down'],
    ])('%s', (_, error, expected) => {
        expect(evaluationErrorMessage(error, 'fallback copy')).toBe(expected)
    })
})
