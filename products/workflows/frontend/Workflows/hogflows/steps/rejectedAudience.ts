import { ApiError } from 'lib/api'

export function isRejectedAudience(error: unknown): error is ApiError & { detail: string } {
    return error instanceof ApiError && error.status === 400 && error.code === 'invalid_input' && !!error.detail
}
