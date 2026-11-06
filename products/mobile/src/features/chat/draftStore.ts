import { EMPTY_QUEUE, type QueueState } from './messageQueue'

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
    queue?: QueueState
    draft: ChatDraft
    unsent?: ChatDraft
}

type Drafts = Record<string, SavedDraft>
const EMPTY: ChatDraft = { text: '', reportIds: [] }
const LIMIT = 50
const MAX_PROJECT_CHARACTERS = 128 * 1024

export class DraftStorageLimitError extends Error {
    constructor() {
        super("Saved messages have reached this device's limit. Remove a queued message before saving more.")
        this.name = 'DraftStorageLimitError'
    }
}

function parseDraft(value: unknown): ChatDraft {
    const record = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
    return {
        text: typeof record.text === 'string' ? record.text : '',
        reportIds: Array.isArray(record.reportIds)
            ? record.reportIds.filter((id): id is string => typeof id === 'string').slice(0, 5)
            : [],
    }
}

function parseQueue(value: unknown): QueueState {
    if (!value || typeof value !== 'object' || !('rows' in value) || !Array.isArray(value.rows)) return EMPTY_QUEUE
    const rows: QueueState['rows'] = []
    for (const row of value.rows) {
        if (!row || typeof row !== 'object' || typeof row.id !== 'string' || typeof row.text !== 'string') continue
        rows.push({
            id: row.id,
            text: row.text,
            attachments: [],
            missingAttachments:
                Number.isSafeInteger(row.missingAttachments) && row.missingAttachments > 0 ? row.missingAttachments : 0,
        })
    }
    return { rows, hold: rows.length ? 'unconfirmed' : null }
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
        const stored = await this.storage.getItem(scope)
        try {
            const value: unknown = JSON.parse(stored ?? '{}')
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
                    queue: parseQueue(saved.queue),
                }
            }
            return result
        } catch {
            return {}
        }
    }

    private async write(
        scope: string,
        key: string,
        saved: SavedDraft,
        drafts: Drafts,
        maxCharacters: number = MAX_PROJECT_CHARACTERS
    ): Promise<void> {
        const previousSize = JSON.stringify(drafts).length
        delete drafts[key]
        if (hasContent(saved.draft) || saved.unsent || saved.queue?.rows.length) {
            drafts[key] = saved
        }
        const keys = Object.keys(drafts)
        for (const stale of keys.slice(0, Math.max(0, keys.length - LIMIT))) {
            if (!drafts[stale]?.queue?.rows.length) delete drafts[stale]
        }
        if (Object.keys(drafts).length) {
            const serialized = JSON.stringify(drafts)
            if (serialized.length > maxCharacters && serialized.length >= previousSize)
                throw new DraftStorageLimitError()
            await this.storage.setItem(scope, serialized)
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
                await this.write(scope, key, { ...saved, draft, unsent: undefined }, drafts)
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
            const drafts = await this.read(scope)
            await this.write(scope, key, { ...drafts[key], draft, unsent }, drafts)
        })
    }

    async beginSend(scope: string, key: string, message: ChatDraft): Promise<(sent: boolean) => Promise<void>> {
        const generation = this.generation
        const handle = { message, key }
        await this.enqueue(async () => {
            if (generation !== this.generation) {
                return
            }
            const id = `${scope}:${key}`
            this.pending.set(id, handle)
            try {
                const drafts = await this.read(scope)
                await this.write(scope, key, { ...drafts[key], draft: EMPTY, unsent: message }, drafts)
            } catch (error) {
                if (this.pending.get(id) === handle) this.pending.delete(id)
                throw error
            }
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
                await this.write(
                    scope,
                    target,
                    { ...drafts[target], unsent: undefined, draft: sent ? typed : restoreUnsent(typed, message) },
                    drafts
                )
            })
    }

    loadQueue(scope: string, key: string): Promise<QueueState> {
        return this.enqueue(async () => (await this.read(scope))[key]?.queue ?? EMPTY_QUEUE)
    }

    saveQueue(scope: string, key: string, queue: QueueState, draft?: ChatDraft): Promise<void> {
        const generation = this.generation
        // File handles cannot survive a restart. Store only a count, so recovery never sends a message without its files.
        const savedQueue: QueueState = {
            hold: queue.hold,
            rows: queue.rows.map(({ id, text, attachments, missingAttachments }) => ({
                id,
                text,
                attachments: [],
                missingAttachments: (missingAttachments ?? 0) + attachments.length,
            })),
        }
        return this.enqueue(async () => {
            if (generation !== this.generation) throw new Error('Session ended')
            const drafts = await this.read(scope)
            await this.write(
                scope,
                key,
                {
                    ...drafts[key],
                    draft: draft ?? drafts[key]?.draft ?? EMPTY,
                    queue: savedQueue,
                },
                drafts
            )
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
            const previousSize = JSON.stringify(drafts).length
            const pending = this.pending.get(`${scope}:${from}`)
            this.pending.delete(`${scope}:${from}`)
            if (pending) {
                pending.key = to
                this.pending.set(`${scope}:${to}`, pending)
            }
            delete drafts[from]
            if (saved) {
                const keyGrowth = Math.max(0, JSON.stringify(to).length - JSON.stringify(from).length)
                await this.write(scope, to, saved, drafts, Math.max(MAX_PROJECT_CHARACTERS, previousSize + keyGrowth))
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
