/** Read snapshots for one inbound request; never reuse across requests. */
export class StateLookupCache {
    private readonly promises = new Map<string, Promise<unknown>>()

    get<T>(scope: string, key: string, load: () => Promise<T>): Promise<T> {
        const scopedKey = JSON.stringify([scope, key])
        const cached = this.promises.get(scopedKey)
        if (cached) {
            return cached as Promise<T>
        }
        const pending = load().catch((error: unknown) => {
            this.promises.delete(scopedKey)
            throw error
        })
        this.promises.set(scopedKey, pending)
        return pending
    }
}
