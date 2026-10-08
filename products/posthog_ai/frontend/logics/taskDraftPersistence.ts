import { v4 as uuid } from 'uuid'

export type DraftRecovery = 'restored' | 'unconfirmed' | null

export interface TaskDraftState {
    runId: string
    draft: string
    queuedText: string
    recovery: DraftRecovery
}

interface SavedTaskDraft {
    version: 1
    revision: string
    updatedAt: number
    runId: string
    draft: string
    queuedText: string
    pendingContent: string
    deliveryUnconfirmed: boolean
}

const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

export function taskDraftStorageKey(userId: string, projectId: number, taskId: string): string {
    return `posthog-ai:task-draft:${userId}:${projectId}:${taskId}`
}

function readDraft(key: string): SavedTaskDraft | null {
    try {
        const raw = localStorage.getItem(key)
        if (!raw) {
            return null
        }
        const value: unknown = JSON.parse(raw)
        if (
            typeof value === 'object' &&
            value !== null &&
            'version' in value &&
            value.version === 1 &&
            'revision' in value &&
            typeof value.revision === 'string' &&
            'updatedAt' in value &&
            typeof value.updatedAt === 'number' &&
            Number.isFinite(value.updatedAt) &&
            value.updatedAt <= Date.now() &&
            Date.now() - value.updatedAt < DRAFT_MAX_AGE_MS &&
            'runId' in value &&
            typeof value.runId === 'string' &&
            'draft' in value &&
            typeof value.draft === 'string' &&
            'queuedText' in value &&
            typeof value.queuedText === 'string' &&
            'pendingContent' in value &&
            typeof value.pendingContent === 'string' &&
            'deliveryUnconfirmed' in value &&
            typeof value.deliveryUnconfirmed === 'boolean'
        ) {
            return value as SavedTaskDraft
        }
        localStorage.removeItem(key)
    } catch {
        // Storage can be unavailable or contain a draft written by an incompatible client.
    }
    return null
}

export class TaskDraftPersistence {
    private pendingContent = ''
    private lastSnapshot = ''
    private revision: string | null = null

    constructor(readonly key: string) {}

    restore(): { draft: string; recovery: DraftRecovery } | null {
        const saved = readDraft(this.key)
        if (!saved) {
            return null
        }
        this.revision = saved.revision
        return {
            draft: [saved.pendingContent, saved.queuedText, saved.draft].filter(Boolean).join('\n\n'),
            recovery: saved.deliveryUnconfirmed ? 'unconfirmed' : 'restored',
        }
    }

    startDelivery(content: string): void {
        this.pendingContent = content
    }

    finishDelivery(state: TaskDraftState): void {
        this.pendingContent = ''
        this.save(state, true)
    }

    save(state: TaskDraftState, onlyIfCurrent = false): void {
        const snapshot = {
            runId: state.runId,
            draft: state.draft,
            queuedText: state.queuedText,
            pendingContent: this.pendingContent,
            deliveryUnconfirmed: !!this.pendingContent || state.recovery === 'unconfirmed',
        }
        const serialized = JSON.stringify(snapshot)
        if (serialized === this.lastSnapshot) {
            return
        }
        this.lastSnapshot = serialized
        try {
            // A response from an older tab must not erase a newer tab's edits.
            if (onlyIfCurrent && readDraft(this.key)?.revision !== this.revision) {
                return
            }
            if (!snapshot.draft && !snapshot.queuedText && !snapshot.pendingContent) {
                localStorage.removeItem(this.key)
                this.revision = null
                return
            }
            const revision = uuid()
            const saved: SavedTaskDraft = { ...snapshot, version: 1, revision, updatedAt: Date.now() }
            localStorage.setItem(this.key, JSON.stringify(saved))
            this.revision = revision
        } catch {
            // Recovery is best-effort; storage failures must not prevent editing or sending.
        }
    }
}
