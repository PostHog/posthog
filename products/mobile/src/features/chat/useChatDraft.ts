import { useCallback, useEffect, useRef, useState } from 'react'
import { AppState } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { track } from '@/lib/analytics'

import { chatDrafts, draftIdentity, draftScope } from './draftPersistence'
import { type ChatDraft, restoreUnsent } from './draftStore'

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
    const latest = useRef(draft)
    const target = useRef<DraftTarget | null>(null)
    const [ready, setReady] = useState(false)
    const mounted = useRef(false)
    const destination = useRef(0)
    const edited = useRef(false)
    const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

    const flush = useCallback((): void => {
        if (saveTimer.current) {
            clearTimeout(saveTimer.current)
            saveTimer.current = null
        }
        const current = target.current
        if (current && draftIdentity() === current.identity) {
            void chatDrafts.save(current.scope, current.key, latest.current).catch(() => undefined)
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
        const previous = target.current
        const adopting = previous?.identity === identity && !previous.key.startsWith('task:') && key.startsWith('task:')
        if (!adopting) {
            edited.current = false
            latest.current = { text: '', reportIds: reportId ? [reportId] : [] }
            setDraft(latest.current)
        }
        target.current = null
        if (!identity) {
            setReady(true)
            return undefined
        }
        void (async () => {
            const scope = await draftScope(identity)
            if (!scope || cancelled) {
                return
            }
            if (adopting && previous) {
                await chatDrafts.move(scope, previous.key, key)
            }
            const saved = await chatDrafts.load(scope, key)
            if (cancelled || draftIdentity() !== identity) {
                return
            }
            if (adopting && previous) {
                previous.key = key
                target.current = previous
            } else {
                target.current = { identity, scope, key }
            }
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
                setReady(true)
            }
        })
        return () => {
            flush()
            mounted.current = false
            cancelled = true
        }
    }, [identity, key, reportId, flush])

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

    return { draft, ready, change, beginSend }
}
