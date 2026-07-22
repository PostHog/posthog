export type ExecHelpEntryKind = 'guide' | 'skill'

export interface ExecHelpEntry {
    id: string
    kind: ExecHelpEntryKind
    title: string
    description: string
    content: string
}

export type ExecHelpEntrySummary = Omit<ExecHelpEntry, 'content'>

/**
 * Runtime catalog for optional exec guidance. Guide entries are bundled today;
 * the same flat ID + kind contract can later include skill-backed entries.
 */
export class ExecHelpCatalog {
    private readonly entriesById: Map<string, ExecHelpEntry>

    constructor(entries: ExecHelpEntry[]) {
        this.entriesById = new Map()
        for (const entry of entries) {
            if (this.entriesById.has(entry.id)) {
                throw new Error(`Duplicate exec help ID: "${entry.id}"`)
            }
            this.entriesById.set(entry.id, entry)
        }
    }

    list(): ExecHelpEntrySummary[] {
        return [...this.entriesById.values()].map(({ content: _content, ...summary }) => summary)
    }

    get(id: string): ExecHelpEntry | undefined {
        return this.entriesById.get(id)
    }
}
