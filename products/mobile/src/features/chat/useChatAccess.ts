import { createContext, useCallback, useEffect, useRef, useState } from 'react'
import { AppState } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { useDataMode } from '@/demo/demoMode'
import { type AiAccess, currentAiAccess, currentAiIdentity, refreshAiOrganization } from '@/features/ai/aiApproval'

import type { ProjectOrganization } from './aiAccess'
import { aiConsentKey, useAiConsentHydrated, useAiConsentStore } from './aiConsentStore'

export type ChatAccess = AiAccess | { kind: 'checking' }

export interface ChatAccessState {
    access: ChatAccess
    rechecking: boolean
    organization?: ProjectOrganization
    accept: () => void
    checkAgain: () => void
}

export const ChatAccessContext = createContext<ChatAccessState | null>(null)

export function useChatAccess(enabled = true): ChatAccessState {
    const dataMode = useDataMode()
    const auth = useAuthStore()
    const identity = currentAiIdentity()
    const consentHydrated = useAiConsentHydrated()
    useAiConsentStore((state) => state.accepted)
    const [verification, setVerification] = useState<{
        identity: string
        failed: boolean
        checking: boolean
        organization?: ProjectOrganization
    } | null>(null)

    const verificationVersion = useRef(0)
    const checkAgain = useCallback((): void => {
        if (!enabled || dataMode !== 'live' || !identity) {
            return
        }
        const version = ++verificationVersion.current
        setVerification({ identity, failed: false, checking: true })
        void refreshAiOrganization(identity).then(
            (organization) => {
                if (currentAiIdentity() === identity && verificationVersion.current === version)
                    setVerification({ identity, failed: false, checking: false, organization })
            },
            () => {
                if (currentAiIdentity() === identity && verificationVersion.current === version)
                    setVerification({ identity, failed: true, checking: false })
            }
        )
    }, [dataMode, enabled, identity])

    useEffect(() => {
        if (!enabled) return
        checkAgain()
        const subscription = AppState.addEventListener('change', (next) => {
            if (next === 'active') checkAgain()
        })
        return () => {
            verificationVersion.current++
            subscription.remove()
        }
    }, [checkAgain, enabled])

    const accept = useCallback((): void => {
        if (identity && currentAiIdentity() === identity && auth.host && auth.user) {
            useAiConsentStore.getState().accept(aiConsentKey(auth.host, auth.user.uuid))
        }
    }, [identity, auth.host, auth.user])

    let access: ChatAccess
    if (dataMode === 'demo') access = { kind: 'ready' }
    else if (
        dataMode === 'loading' ||
        !consentHydrated ||
        !verification ||
        verification.identity !== identity ||
        verification.checking
    )
        access = { kind: 'checking' }
    else if (verification.failed) access = { kind: 'org_unknown' }
    else access = currentAiAccess(verification.organization)
    return {
        access,
        rechecking: verification?.checking ?? false,
        organization: verification?.identity === identity ? verification.organization : undefined,
        accept,
        checkAgain,
    }
}
