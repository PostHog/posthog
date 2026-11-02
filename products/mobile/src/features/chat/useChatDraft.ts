import { useCallback, useEffect, useRef, useState } from 'react'
import { AppState } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { track } from '@/lib/analytics'

import { chatDrafts, draftIdentity, draftScope } from './draftPersistence'
import { type ChatDraft, DraftStorageLimitError, restoreUnsent } from './draftStore'
import { EMPTY_QUEUE, type QueueAction, type QueueState, queueReducer } from './messageQueue'

interface DraftTarget {
    identity: string
    scope: string
    key: string
}

export function useChatDraft(
    taskId: string | null,
    reportId: string | undefined,
    demo = false
): {
    draft: ChatDraft
    queue: QueueState
    queuePending: boolean
    queueError: string | undefined
    dismissQueueError: () => void
    updateQueue: (action: QueueAction, clearComposer?: boolean) => Promise<boolean>
    ready: boolean
    change: (draft: ChatDraft) => void
    beginSend: (message: ChatDraft) => Promise<(sent: boolean) => Promise<void>>
} {
    const signedIn = useAuthStore((state) => state.signedIn)
    const host = useAuthStore((state) => state.host)
    const userId = useAuthStore((state) => state.user?.uuid)
    const projectId = useAuthStore((state) => state.projectId)
    const identity = !demo && signedIn && host && userId && projectId !== null ? draftIdentity() : null
    const key = taskId ? `task:${taskId}` : reportId ? `report:${reportId}` : 'new-chat'
    const initial = { text: '', reportIds: reportId ? [reportId] : [] }
    const [draft, setDraft] = useState<ChatDraft>(initial)
    const [queue, setQueue] = useState<QueueState>(EMPTY_QUEUE)
    const queueRef = useRef(queue)
    const queueBusy = useRef(false)
    const queueWrite = useRef<Promise<void>>(Promise.resolve())
    const queueClear = useRef<{ draft: ChatDraft; committed: boolean } | null>(null)
    const [queuePending, setQueuePending] = useState(false)
    const [queueError, setQueueError] = useState<string>()
    const latest = useRef(draft)
    const target = useRef<DraftTarget | null>(null)
    const [ready, setReady] = useState(false)
    const mounted = useRef(false)
    const destination = useRef(0)
    const previousDestination = useRef({ identity, key })
    const edited = useRef(false)
    const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

    const flush = useCallback((): void => {
        if (saveTimer.current) {
            clearTimeout(saveTimer.current)
            saveTimer.current = null
        }
        const current = target.current
        if (current && draftIdentity() === current.identity) {
            const typed = latest.current
            const pendingClear = queueClear.current
            const save = (): void => {
                if (draftIdentity() !== current.identity) return
                const draft =
                    pendingClear?.committed && pendingClear.draft === typed
                        ? { text: '', reportIds: typed.reportIds }
                        : typed
                void chatDrafts.save(current.scope, current.key, draft).catch(() => undefined)
            }
            if (queueBusy.current) void queueWrite.current.then(save)
            else save()
        }
    }, [])

    const change = useCallback(
        (next: ChatDraft): void => {
            edited.current = true
            latest.current = next
            setDraft(next)
            if (saveTimer.current) {
                clearTimeout(saveTimer.current)
            }
            saveTimer.current = setTimeout(flush, 400)
        },
        [flush]
    )

    useEffect(() => {
        const subscription = AppState.addEventListener('change', (state) => {
            if (state !== 'active') {
                flush()
            }
        })
        return () => subscription.remove()
    }, [flush])

    useEffect(() => {
        let cancelled = false
        mounted.current = true
        destination.current++
        setReady(false)
        queueBusy.current = false
        setQueuePending(false)
        setQueueError(undefined)
        const previous = target.current
        const prior = previousDestination.current
        const adopting = prior.identity === identity && !prior.key.startsWith('task:') && key.startsWith('task:')
        previousDestination.current = { identity, key }
        if (!adopting) {
            edited.current = false
            latest.current = { text: '', reportIds: reportId ? [reportId] : [] }
            setDraft(latest.current)
            queueRef.current = EMPTY_QUEUE
            setQueue(EMPTY_QUEUE)
        }
        target.current = null
        if (!identity) {
            setReady(true)
            return () => {
                mounted.current = false
            }
        }
        void (async () => {
            const scope = await draftScope(identity)
            if (!scope || cancelled) {
                return
            }
            if (adopting && previous) {
                const source = previous.key
                previous.key = key
                await chatDrafts.move(scope, source, key)
            }
            const saved = await chatDrafts.load(scope, key)
            const savedQueue = await chatDrafts.loadQueue(scope, key)
            if (cancelled || draftIdentity() !== identity) {
                return
            }
            if (adopting && previous) {
                target.current = previous
            } else {
                target.current = { identity, scope, key }
            }
            const restored = adopting
                ? {
                      ...savedQueue,
                      hold: queueRef.current.hold,
                      rows: savedQueue.rows.map(
                          (row) => queueRef.current.rows.find((live) => live.id === row.id) ?? row
                      ),
                  }
                : savedQueue
            queueRef.current = restored
            setQueue(restored)
            if (!edited.current && saved) {
                latest.current = saved
                setDraft(saved)
                if (saved.text.trim()) {
                    track('mobile_chat_draft_restored', {
                        text_length: saved.text.length,
                        report_count: saved.reportIds.length,
                    })
                }
            } else if (edited.current) {
                await chatDrafts.save(scope, key, latest.current)
            }
            setReady(true)
        })().catch(() => {
            if (!cancelled) {
                setQueueError("Couldn't load saved messages. Close and reopen this chat to try again.")
                setReady(true)
            }
        })
        return () => {
            flush()
            mounted.current = false
            cancelled = true
        }
    }, [identity, key, reportId, flush])

    const updateQueue = useCallback(
        async (action: QueueAction, clearComposer = false): Promise<boolean> => {
            const current = target.current
            const mine = destination.current
            if (queueBusy.current && (action.type === 'enqueue' || action.type === 'remove')) return false
            while (queueBusy.current) await queueWrite.current
            if (mine !== destination.current) return false
            if (!ready || (identity && (!current || draftIdentity() !== current.identity))) {
                if (mine === destination.current && mounted.current)
                    setQueueError("Couldn't load saved messages. Close and reopen this chat to try again.")
                return false
            }
            queueBusy.current = true
            let finish!: () => void
            queueWrite.current = new Promise<void>((resolve) => {
                finish = resolve
            })
            setQueuePending(true)
            setQueueError(undefined)
            const next = queueReducer(queueRef.current, action)
            if (action.type === 'hold') {
                queueRef.current = next
                setQueue(next)
            }
            const typed = latest.current
            const cleared = { text: '', reportIds: typed.reportIds }
            const clearing = clearComposer ? { draft: typed, committed: false } : null
            queueClear.current = clearing
            try {
                if (current)
                    await chatDrafts.saveQueue(current.scope, current.key, next, clearComposer ? cleared : undefined)
                if (clearing) clearing.committed = true
                if (
                    mine !== destination.current ||
                    (current && draftIdentity() !== current.identity) ||
                    !mounted.current
                )
                    return false
                queueRef.current = next
                setQueue(next)
                if (clearComposer && latest.current === typed) change(cleared)
                return true
            } catch (error) {
                if (mine === destination.current && mounted.current) {
                    setQueueError(
                        error instanceof DraftStorageLimitError
                            ? error.message
                            : "Couldn't save queued messages on this device. Try again before closing the chat."
                    )
                }
                return false
            } finally {
                if (queueClear.current === clearing) queueClear.current = null
                finish()
                if (mine === destination.current) {
                    queueBusy.current = false
                    setQueuePending(false)
                }
            }
        },
        [change, identity, ready]
    )

    const beginSend = useCallback(
        async (message: ChatDraft): Promise<(sent: boolean) => Promise<void>> => {
            const current = target.current
            const sendingIdentity = draftIdentity()
            const sendingDestination = destination.current
            let settlement: Promise<((sent: boolean) => Promise<void>) | undefined> | undefined
            if (current && draftIdentity() === current.identity) {
                // A storage failure must not prevent the person from sending their message.
                settlement = chatDrafts.beginSend(current.scope, current.key, message).catch(() => undefined)
            }
            change({ text: '', reportIds: message.reportIds })
            const settle = await settlement
            return async (sent): Promise<void> => {
                if (draftIdentity() !== sendingIdentity) {
                    return
                }
                await settle?.(sent).catch(() => undefined)
                if (
                    mounted.current &&
                    !sent &&
                    (current ? target.current === current : destination.current === sendingDestination)
                ) {
                    change(restoreUnsent(latest.current, message))
                }
            }
        },
        [change]
    )

    const dismissQueueError = useCallback((): void => setQueueError(undefined), [])
    return { draft, ready, change, beginSend, queue, queuePending, queueError, dismissQueueError, updateQueue }
}
