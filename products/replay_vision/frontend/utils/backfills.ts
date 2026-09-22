// The filter row fits only the UUID prefix. The Backfills table shows the full ID for comparison.
export function shortBackfillId(id: string): string {
    return id.slice(0, 8)
}
