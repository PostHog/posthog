import * as Crypto from 'expo-crypto'
import { Linking } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { HANDOFF_PARAM, handoffMarker, isMobileHandoffUrl, takeHandoff } from '../../frontend/handoffProtocol'
import { track, trackWhenReady } from './analytics'
import { isInternalBuild } from './environment'

function enabled(): boolean {
    return isInternalBuild && process.env.EXPO_PUBLIC_POSTHOG_HANDOFF === '1'
}

export function receiveSessionHandoff(path: string): string {
    try {
        const url = new URL(path)
        if (!isMobileHandoffUrl(url)) {
            return path
        }
        const id = takeHandoff(url, Date.now())
        if (id && enabled()) {
            trackWhenReady('mobile_session_handoff_received', { handoff_id: id, session_continuity: 'correlated' })
        }
        return url.toString()
    } catch {
        return path
    }
}

export function openPostHogUrl(path: string): Promise<unknown> {
    let target = path
    if (enabled()) {
        try {
            const url = new URL(path)
            const { status, host, projectId } = useAuthStore.getState()
            if (
                status === 'signed_in' &&
                host &&
                projectId !== null &&
                url.protocol === 'https:' &&
                url.origin === new URL(host).origin &&
                !url.username &&
                !url.password &&
                !url.hash &&
                url.pathname.startsWith(`/project/${projectId}/`)
            ) {
                const id = Crypto.randomUUID()
                url.hash = new URLSearchParams({ [HANDOFF_PARAM]: handoffMarker(id, Date.now()) }).toString()
                target = url.toString()
                track('mobile_session_handoff_started', { handoff_id: id, session_continuity: 'correlated' })
            }
        } catch {
            // Navigation still works when a URL cannot participate in the experiment.
        }
    }
    return Linking.openURL(target)
}
