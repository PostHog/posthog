import { useCallback, useEffect, useState } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'

import { orgAiSettingsUrl, projectOrganization } from './aiAccess'
import { aiConsentKey, useAiConsentHydrated, useAiConsentStore } from './aiConsentStore'

export type ChatAccess =
    | { kind: 'checking' }
    | { kind: 'org_blocked'; organizationName: string | null; settingsUrl: string | null }
    | { kind: 'org_unknown' }
    | { kind: 'needs_consent' }
    | { kind: 'ready' }

export interface ChatAccessState {
    access: ChatAccess
    /** True while a "Check again" reload of the account runs. */
    rechecking: boolean
    accept: () => void
    checkAgain: () => void
}

/**
 * Whether the chat may send. The organization must allow third-party AI processing, as the web requires, and the
 * person must have agreed on this device to send chat data to PostHog AI. Demo chats send nothing, so they skip both.
 */
export function useChatAccess(): ChatAccessState {
    const dataMode = useDataMode()
    const scope = useProjectScope()
    const host = useAuthStore((state) => state.host)
    const userUuid = useAuthStore((state) => state.user?.uuid)
    const organizations = useAuthStore((state) => state.organizations)
    const projects = useAuthStore((state) => state.projects)
    const projectId = useAuthStore((state) => state.projectId)
    const accountLoading = useAuthStore((state) => state.accountLoading)
    const reloadAccount = useAuthStore((state) => state.reloadAccount)
    const consentHydrated = useAiConsentHydrated()
    const consentKey = host && userUuid ? aiConsentKey(host, userUuid) : null
    const consented = useAiConsentStore((state) => (consentKey ? state.accepted[consentKey] === true : false))
    const organization = projectOrganization(organizations, projects, projectId)
    const live = dataMode === 'live'
    const unknown = live && organization.status === 'unknown'
    const [accountChecked, setAccountChecked] = useState(false)

    // A session restored from before the app stored the flag has none until the account reloads.
    useEffect(() => {
        if (!unknown || accountChecked) {
            return undefined
        }
        let current = true
        reloadAccount().finally(() => {
            if (current) {
                setAccountChecked(true)
            }
        })
        return () => {
            current = false
        }
    }, [unknown, accountChecked, reloadAccount])

    const accept = useCallback((): void => {
        if (consentKey) {
            useAiConsentStore.getState().accept(consentKey)
        }
    }, [consentKey])
    const checkAgain = useCallback((): void => {
        void reloadAccount()
    }, [reloadAccount])

    const access = ((): ChatAccess => {
        if (dataMode === 'loading') {
            return { kind: 'checking' }
        }
        if (dataMode === 'demo') {
            return { kind: 'ready' }
        }
        if (organization.status === 'unknown') {
            return accountChecked && !accountLoading ? { kind: 'org_unknown' } : { kind: 'checking' }
        }
        if (organization.status === 'not_approved') {
            return {
                kind: 'org_blocked',
                organizationName: organization.name,
                settingsUrl: scope ? orgAiSettingsUrl(scope) : null,
            }
        }
        if (!consentHydrated) {
            return { kind: 'checking' }
        }
        return consented ? { kind: 'ready' } : { kind: 'needs_consent' }
    })()

    return { access, rechecking: accountLoading, accept, checkAgain }
}
