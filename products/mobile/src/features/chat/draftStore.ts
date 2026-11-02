export interface ChatDraft {
    text: string
    reportIds: string[]
}

export interface DraftStorage {
    getItem: (key: string) => Promise<string | null>
    setItem: (key: string, value: string) => Promise<void>
    removeItem: (key: string) => Promise<void>
}

interface SavedDraft {
    draft: ChatDraft
    unsent?: ChatDraft
}

type Drafts = Record<string, SavedDraft>
const EMPTY: ChatDraft = { text: '', reportIds: [] }
const LIMIT = 50

function parseDraft(value: unknown): ChatDraft {
    const record = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
    return {
        text: typeof record.text === 'string' ? record.text : '',
        reportIds: Array.isArray(record.reportIds)
            ? record.reportIds.filter((id): id is string => typeof id === 'string').slice(0, 5)
            : [],
    }
}

function hasContent(draft: ChatDraft): boolean {
    return draft.text.trim().length > 0 || draft.reportIds.length > 0
}

export function restoreUnsent(typed: ChatDraft, unsent: ChatDraft): ChatDraft {
    return {
        text: typed.text.trim() ? typed.text : unsent.text,
        reportIds: typed.reportIds.length ? typed.reportIds : unsent.reportIds,
    }
}

/** Serializes device writes so a slow save cannot resurrect a cleared or older draft. */
export class DraftStore {
    private queue: Promise<unknown> = Promise.resolve()
    private pending = new Map<string, { message: ChatDraft; key: string }>()
    private generation = 0

    constructor(private readonly storage: DraftStorage) {}

    private enqueue<T>(work: () => Promise<T>): Promise<T> {
        const result = this.queue.then(work)
        this.queue = result.catch(() => undefined)
        return result
    }

    private async read(scope: string): Promise<Drafts> {
        try {
            const value: unknown = JSON.parse((await this.storage.getItem(scope)) ?? '{}')
            if (!value || typeof value !== 'object' || Array.isArray(value)) {
                return {}
            }
            const result: Drafts = {}
            for (const [key, entry] of Object.entries(value)) {
                if (!entry || typeof entry !== 'object') {
                    continue
                }
                const saved = entry as Record<string, unknown>
                result[key] = {
                    draft: parseDraft(saved.draft),
                    ...(saved.unsent ? { unsent: parseDraft(saved.unsent) } : {}),
                }
            }
            return result
        } catch {
            return {}
        }
    }

    private async write(scope: string, key: string, saved: SavedDraft, drafts: Drafts): Promise<void> {
        delete drafts[key]
        if (hasContent(saved.draft) || saved.unsent) {
            drafts[key] = saved
        }
        const keys = Object.keys(drafts)
        for (const stale of keys.slice(0, Math.max(0, keys.length - LIMIT))) {
            delete drafts[stale]
        }
        if (Object.keys(drafts).length) {
            await this.storage.setItem(scope, JSON.stringify(drafts))
        } else {
            await this.storage.removeItem(scope)
        }
    }

    load(scope: string, key: string): Promise<ChatDraft | null> {
        return this.enqueue(async () => {
            const drafts = await this.read(scope)
            const saved = drafts[key]
            if (!saved) {
                return null
            }
            let draft = saved.draft
            if (saved.unsent && !this.pending.has(`${scope}:${key}`)) {
                draft = restoreUnsent(draft, saved.unsent)
                await this.write(scope, key, { draft }, drafts)
            }
            return hasContent(draft) ? draft : null
        })
    }

    save(scope: string, key: string, draft: ChatDraft): Promise<void> {
        const generation = this.generation
        return this.enqueue(async () => {
            if (generation !== this.generation) {
                return
            }
            const unsent = this.pending.get(`${scope}:${key}`)?.message
            await this.write(scope, key, { draft, ...(unsent ? { unsent } : {}) }, await this.read(scope))
        })
    }

    async beginSend(scope: string, key: string, message: ChatDraft): Promise<(sent: boolean) => Promise<void>> {
        const generation = this.generation
        const handle = { message, key }
        await this.enqueue(async () => {
            if (generation !== this.generation) {
                return
            }
            this.pending.set(`${scope}:${key}`, handle)
            await this.write(scope, key, { draft: EMPTY, unsent: message }, await this.read(scope))
        })
        return (sent) =>
            this.enqueue(async () => {
                if (generation !== this.generation) {
                    return
                }
                const target = handle.key
                const id = `${scope}:${target}`
                if (this.pending.get(id) !== handle) {
                    return
                }
                this.pending.delete(id)
                const drafts = await this.read(scope)
                const typed = drafts[target]?.draft ?? EMPTY
                await this.write(scope, target, { draft: sent ? typed : restoreUnsent(typed, message) }, drafts)
            })
    }

    move(scope: string, from: string, to: string): Promise<void> {
        const generation = this.generation
        return this.enqueue(async () => {
            if (generation !== this.generation || from === to) {
                return
            }
            const drafts = await this.read(scope)
            const saved = drafts[from]
            const pending = this.pending.get(`${scope}:${from}`)
            this.pending.delete(`${scope}:${from}`)
            if (pending) {
                pending.key = to
                this.pending.set(`${scope}:${to}`, pending)
            }
            delete drafts[from]
            if (saved) {
                await this.write(scope, to, saved, drafts)
            }
        })
    }

    clear(scopes: string[]): Promise<void> {
        this.generation++
        this.pending.clear()
        return this.enqueue(async () => {
            await Promise.all(scopes.map((scope) => this.storage.removeItem(scope)))
        })
    }
}
