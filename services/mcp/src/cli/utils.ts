export function errorCode(error: unknown): unknown {
    return typeof error === 'object' && error !== null && 'code' in error
        ? (error as { code?: unknown }).code
        : undefined
}
