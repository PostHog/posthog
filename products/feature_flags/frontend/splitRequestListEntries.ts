// A pasted "a.com, b.com" arrives as one entry, and the API rejects the whole list over it.
export function splitRequestListEntries(entries: string[]): string[] {
    return Array.from(
        new Set(
            entries
                .flatMap((entry) => entry.split(','))
                .map((entry) => entry.trim())
                .filter(Boolean)
        )
    )
}
