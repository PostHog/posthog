let pendingOperations = 0

export function isAppReloadBlocked(): boolean {
    return pendingOperations > 0
}

export async function withAppReloadBlocked<T>(operation: () => Promise<T>): Promise<T> {
    pendingOperations++
    try {
        return await operation()
    } finally {
        pendingOperations--
    }
}
