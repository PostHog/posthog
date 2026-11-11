export type NotebookVisit = { markdown: string; viewedAt: number }
type StoredVisit = NotebookVisit & { scope: string }

const STORAGE_KEY = 'notebook-last-visits'
const MAX_MARKDOWN_LENGTH = 500_000
const MAX_TOTAL_LENGTH = 2_000_000
const MAX_VISITS = 10

export class NotebookVisitStorage {
    private static readAll(): StoredVisit[] {
        try {
            const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
            if (!Array.isArray(value)) {
                return []
            }
            return value.filter(
                (entry): entry is StoredVisit =>
                    !!entry &&
                    typeof entry.scope === 'string' &&
                    typeof entry.markdown === 'string' &&
                    entry.markdown.length <= MAX_MARKDOWN_LENGTH &&
                    typeof entry.viewedAt === 'number' &&
                    Number.isFinite(new Date(entry.viewedAt).getTime())
            )
        } catch {
            return []
        }
    }

    static read(scope: string): NotebookVisit | null {
        return this.readAll().find((entry) => entry.scope === scope) ?? null
    }

    static write(scope: string, markdown: string): void {
        const entries = this.readAll().filter((entry) => entry.scope !== scope)
        if (markdown.length <= MAX_MARKDOWN_LENGTH) {
            entries.unshift({ scope, markdown, viewedAt: Date.now() })
        }
        let remaining = MAX_TOTAL_LENGTH
        const retained = entries.slice(0, MAX_VISITS).filter((entry) => {
            remaining -= JSON.stringify(entry).length
            return remaining >= 0
        })
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(retained))
        } catch {
            // Storage can be disabled or full; opening and editing the notebook must still work.
        }
    }
}
