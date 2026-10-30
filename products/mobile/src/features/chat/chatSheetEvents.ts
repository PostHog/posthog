import { useEffect, useRef } from 'react'

import { track } from '@/lib/analytics'
import type { ChatOrigin } from '@/model/types'

import { ISSUE_OBJECT_TYPE, RECORDING_OBJECT_TYPE } from './objectContext'

export const CHAT_SHEET_ENTRIES = [
    'chats_list',
    'chats_search',
    'chats_empty',
    'compose',
    'report',
    'report_task',
    'inbox_menu',
    'task',
    'issue',
    'replay',
] as const

export type ChatSheetEntry = (typeof CHAT_SHEET_ENTRIES)[number]

const CHAT_ORIGINS: readonly ChatOrigin[] = ['chat', 'report', 'session']

export interface ChatSheetSource {
    entry: ChatSheetEntry
    /** The Chats list row's origin. Null for every other entry. */
    origin: ChatOrigin | null
}

export function chatSheetSource(params: {
    entry?: string
    origin?: string
    reportId?: string
    taskId?: string
    objectType?: string
}): ChatSheetSource {
    const origin = CHAT_ORIGINS.find((value) => value === params.origin) ?? null
    const named = CHAT_SHEET_ENTRIES.find((value) => value === params.entry)
    if (named) {
        return { entry: named, origin }
    }
    if (params.reportId) {
        return { entry: 'report', origin }
    }
    if (params.objectType === ISSUE_OBJECT_TYPE) {
        return { entry: 'issue', origin }
    }
    if (params.objectType === RECORDING_OBJECT_TYPE) {
        return { entry: 'replay', origin }
    }
    if (params.taskId) {
        return { entry: 'task', origin }
    }
    return { entry: 'compose', origin }
}

interface ChatSheetOpen extends ChatSheetSource {
    hasContext: boolean
    resumed: boolean
}

/**
 * Sends `mobile_chat_sheet_opened` on mount and `mobile_chat_sheet_closed` on unmount. The unmount also covers the
 * Android back button, which pops the modal route without the sheet's own close.
 */
export function useChatSheetEvents(
    open: ChatSheetOpen,
    runId: string | null
): { countSent: () => void; countNewChat: () => void } {
    const opened = useRef(open)
    const sent = useRef(0)
    const newChats = useRef(0)
    const hadRun = useRef(false)

    useEffect(() => {
        if (runId) {
            hadRun.current = true
        }
    }, [runId])

    useEffect(() => {
        const { entry, origin, hasContext, resumed } = opened.current
        const openedAt = Date.now()
        track('mobile_chat_sheet_opened', { entry, origin, has_context: hasContext, resumed })
        return () => {
            track('mobile_chat_sheet_closed', {
                entry,
                messages_sent: sent.current,
                new_chats: newChats.current,
                had_run: hadRun.current,
                dwell_s: Math.round((Date.now() - openedAt) / 1000),
            })
        }
    }, [])

    const counters = useRef({
        countSent: (): void => {
            sent.current += 1
        },
        countNewChat: (): void => {
            newChats.current += 1
        },
    })
    return counters.current
}
