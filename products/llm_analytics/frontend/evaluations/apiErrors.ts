import { ApiError } from 'lib/api'

function firstStringIn(value: unknown): string | null {
    if (typeof value === 'string' && value.trim().length > 0) {
        return value
    }
    if (Array.isArray(value)) {
        for (const item of value) {
            const nested = firstStringIn(item)
            if (nested) {
                return nested
            }
        }
    }
    if (value && typeof value === 'object') {
        for (const nested of Object.values(value as Record<string, unknown>)) {
            const found = firstStringIn(nested)
            if (found) {
                return found
            }
        }
    }
    return null
}

export function evaluationErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError) {
        // Prefer DRF's top-level detail so that APIException payloads like
        // {type: "validation_error", code: "invalid", detail: "..."} don't show "validation_error".
        if (error.detail) {
            return error.detail
        }
        // Fall back to walking serializer field errors like {"enabled": ["..."]}.
        if (error.data && typeof error.data === 'object') {
            const fieldMessage = firstStringIn(error.data)
            if (fieldMessage) {
                return fieldMessage
            }
        }
        if (error.message && !error.message.startsWith('Non-OK response')) {
            return error.message
        }
    } else if (error instanceof Error && error.message) {
        return error.message
    }
    return fallback
}
