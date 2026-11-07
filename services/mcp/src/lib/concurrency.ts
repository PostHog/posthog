export async function mapWithConcurrency<T, R>(
    items: readonly T[],
    limit: number,
    fn: (item: T, index: number) => Promise<R>
): Promise<R[]> {
    if (!Number.isInteger(limit) || limit < 1) {
        throw new Error(`mapWithConcurrency needs a positive integer limit, got ${limit}`)
    }
    const results: R[] = new Array(items.length)
    let nextIndex = 0
    const worker = async (): Promise<void> => {
        for (;;) {
            const index = nextIndex++
            if (index >= items.length) {
                return
            }
            results[index] = await fn(items[index]!, index)
        }
    }
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
    return results
}
