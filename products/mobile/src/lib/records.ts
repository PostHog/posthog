export function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function asRecord(value: unknown): Record<string, unknown> | undefined {
    return isRecord(value) ? value : undefined
}
