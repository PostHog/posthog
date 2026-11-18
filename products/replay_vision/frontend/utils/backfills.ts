// The filter row fits only the UUID prefix. The backfill history table shows the full ID for comparison.
export function shortBackfillId(id: string): string {
    return id.slice(0, 8)
}
