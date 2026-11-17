import { useEffect } from 'react'
import { create } from 'zustand'

import { type AuthState, useAuthStore } from '@/auth/authStore'

import { accountLabel } from './accountLabel'

/** What just happened to the active account. Home names neither the account nor the project, so a toast does. */
export type AccountNotice = { kind: 'switched' } | { kind: 'added' } | { kind: 'signed_out'; left: string }

interface PostedNotice {
    notice: AccountNotice
    at: number
}

// A notice waits for the start page, which mounts only after the store finishes the switch. One that nobody shows
// in this time belongs to an earlier action.
const NOTICE_TTL_MS = 10_000

const useAccountNoticeStore = create<{ posted: PostedNotice | null }>(() => ({ posted: null }))

export function postAccountNotice(notice: AccountNotice): void {
    useAccountNoticeStore.setState({ posted: { notice, at: Date.now() } })
}

export interface AccountNoticeText {
    text: string
    detail: string | null
}

export function accountNoticeText(
    notice: AccountNotice,
    state: Pick<AuthState, 'accounts' | 'activeAccountKey' | 'projectName'>
): AccountNoticeText | null {
    const active = state.accounts.find((account) => account.key === state.activeAccountKey)
    if (!active) {
        return null
    }
    const label = accountLabel(active, state.accounts)
    switch (notice.kind) {
        case 'switched':
            return state.projectName
                ? {
                      text: `Switched to ${state.projectName}`,
                      detail: active.user ? label : `The${label.slice('the'.length)}`,
                  }
                : { text: `Switched to ${label}`, detail: null }
        case 'added':
            return { text: `Added ${label}`, detail: state.projectName }
        case 'signed_out':
            return { text: `Signed out of ${notice.left}`, detail: `Now using ${label}` }
    }
}

/** Shows the latest account notice once, through the start page's toast. */
export function useAccountNoticeToast(show: (text: string, detail: string | undefined) => void): void {
    const posted = useAccountNoticeStore((state) => state.posted)
    useEffect(() => {
        if (!posted) {
            return
        }
        useAccountNoticeStore.setState({ posted: null })
        if (Date.now() - posted.at > NOTICE_TTL_MS) {
            return
        }
        const message = accountNoticeText(posted.notice, useAuthStore.getState())
        if (message) {
            show(message.text, message.detail ?? undefined)
        }
    }, [posted, show])
}
