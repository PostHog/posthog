import PostHog from 'posthog-react-native'
import { AppState, Platform } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'

import { type AnalyticsProperties, setAnalyticsClient } from './analytics'
import { DEMO_REPLAY_CONFIG, DemoReplay } from './demoReplay'
import { appVariant, hostKind, isInternalBuild, updateChannel } from './environment'
import { setFeatureFlags } from './featureFlags'

const DEFAULT_HOST = 'https://us.i.posthog.com'
let initialized = false

function definedProperties(
    properties: AnalyticsProperties | undefined
): Record<string, string | number | boolean | null> {
    const result: Record<string, string | number | boolean | null> = {}
    for (const [key, value] of Object.entries(properties ?? {})) {
        if (value !== undefined) {
            result[key] = value
        }
    }
    return result
}

function signedInProjectId(): number | null {
    const { status, projectId } = useAuthStore.getState()
    return status === 'signed_in' ? projectId : null
}

// A self-hosted address can name a customer, so events carry only the kind of host, never the host itself.
// `data_mode` is null until the persisted demo flag loads, because before that `enabled` is only the build default.
function superProperties(): Record<string, string | number | null> {
    const { host } = useAuthStore.getState()
    const demo = useDemoMode.getState().enabled
    return {
        app_variant: appVariant,
        update_channel: updateChannel,
        api_host_kind: host ? hostKind(host) : null,
        data_mode: useDemoMode.persist.hasHydrated() ? (demo ? 'demo' : 'live') : null,
        project_id: signedInProjectId(),
    }
}

// Expo inlines `EXPO_PUBLIC_*` variables at build time, so they must be read as literal `process.env` members.
export function initAnalytics(): void {
    const apiKey = process.env.EXPO_PUBLIC_POSTHOG_KEY
    if (!apiKey || initialized) {
        return
    }
    initialized = true
    const posthog = new PostHog(apiKey, {
        host: process.env.EXPO_PUBLIC_POSTHOG_HOST || DEFAULT_HOST,
        captureAppLifecycleEvents: true,
        before_send: (event) => {
            if (!event || event.event !== 'Application Opened') {
                return event
            }
            // The SDK adds the launch URL, which can contain OAuth credentials or private object labels.
            const properties = { ...event.properties }
            delete properties.url
            return { ...event, properties }
        },
        capturePushNotificationSubscriptions: false,
        capturePushNotificationOpened: false,
        rageClickConfig: { enabled: false },
        enableSessionReplay: false,
        enablePersistSessionIdAcrossRestart: isInternalBuild && process.env.EXPO_PUBLIC_POSTHOG_HANDOFF === '1',
        sessionReplayConfig: DEMO_REPLAY_CONFIG,
    })
    const replay = new DemoReplay(posthog)
    const syncReplay = (): void => {
        replay.setAllowed(
            process.env.EXPO_PUBLIC_POSTHOG_REPLAY === '1' &&
                isInternalBuild &&
                (Platform.OS === 'ios' || Platform.OS === 'android') &&
                useDemoMode.persist.hasHydrated() &&
                useDemoMode.getState().enabled &&
                useAuthStore.getState().status === 'signed_out'
        )
    }
    const registerSuperProperties = (): void => {
        void posthog.register(superProperties())
    }
    let flagContext: string | undefined
    let flagRequest = 0
    const syncFlagContext = (force = false): void => {
        const { status, host, user } = useAuthStore.getState()
        const projectId = signedInProjectId()
        const email = status === 'signed_in' && user?.anonymizeData === false ? user.email.trim().toLowerCase() : null
        const context = JSON.stringify([status, host, user?.uuid, user?.anonymizeData, email, projectId])
        if (context === flagContext && !force) {
            return
        }
        if (context !== flagContext) {
            setFeatureFlags({})
        }
        flagContext = context
        const request = ++flagRequest
        posthog.resetPersonPropertiesForFlags(false)
        posthog.setPersonPropertiesForFlags({ project_id: projectId, email }, false)
        if (status !== 'signed_in' || !user) {
            return
        }
        void posthog
            .reloadFeatureFlagsAsync()
            .then((flags) => {
                if (request === flagRequest) {
                    setFeatureFlags(flags ?? {})
                }
            })
            .catch(() => {
                if (request === flagRequest) {
                    setFeatureFlags({})
                }
            })
    }
    setFeatureFlags({})
    registerSuperProperties()
    syncFlagContext()
    syncReplay()
    useAuthStore.subscribe((state, previous) => {
        syncReplay()
        if (
            state.host !== previous.host ||
            state.status !== previous.status ||
            state.projectId !== previous.projectId ||
            state.user?.uuid !== previous.user?.uuid ||
            state.user?.email !== previous.user?.email ||
            state.user?.anonymizeData !== previous.user?.anonymizeData
        ) {
            registerSuperProperties()
            syncFlagContext()
        }
    })
    useDemoMode.subscribe((state, previous) => {
        if (state.enabled !== previous.enabled) {
            registerSuperProperties()
            syncReplay()
        }
    })
    useDemoMode.persist.onFinishHydration(() => {
        registerSuperProperties()
        syncReplay()
    })
    AppState.addEventListener('change', (state) => {
        if (state === 'active') {
            syncFlagContext(true)
        }
    })
    setAnalyticsClient({
        capture: (event, properties) => posthog.capture(event, definedProperties(properties)),
        screen: (name, properties) => void posthog.screen(name, definedProperties(properties)),
        captureError: (error) => posthog.captureException(error),
        identify: (distinctId) => posthog.identify(distinctId),
        reset: () => {
            posthog.reset()
            // reset() drops registered super properties and person properties for flags with the identity.
            flagContext = undefined
            setFeatureFlags({})
            registerSuperProperties()
            syncFlagContext()
        },
    })
}
