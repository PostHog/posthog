import { ApiError } from 'lib/api'

import { classifySendFailure } from './sendFailure'

describe('classifySendFailure', () => {
    const fallback = 'Failed to send message. Please try again.'

    it('treats a lost connection (no status) as retryable and keeps the fallback message', () => {
        expect(classifySendFailure(new ApiError('boom'), fallback)).toEqual({
            retryable: true,
            message: fallback,
        })
    })

    it('treats a 5xx as retryable and surfaces the backend cause', () => {
        const error = new ApiError('Agent server request timed out', 504, undefined, {
            error: 'Agent server request timed out',
        })
        expect(classifySendFailure(error, fallback)).toEqual({
            retryable: true,
            message: 'Agent server request timed out',
        })
    })

    it('treats a 4xx as not retryable and surfaces the run-state cause', () => {
        const error = new ApiError('No active sandbox for this task run', 400, undefined, {
            error: 'No active sandbox for this task run',
        })
        expect(classifySendFailure(error, fallback)).toEqual({
            retryable: false,
            message: 'No active sandbox for this task run',
        })
    })

    it('falls back for a non-ApiError', () => {
        expect(classifySendFailure(new Error('unexpected'), fallback)).toEqual({
            retryable: false,
            message: fallback,
        })
    })
})
