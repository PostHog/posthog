import PostHog from 'posthog-react-native'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'

import { type AnalyticsProperties, setAnalyticsClient } from './analytics'
import { appVariant, hostKind, updateChannel } from './environment'

const DEFAULT_HOST = 'https://us.i.posthog.com'

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

// A self-hosted address can name a customer, so events carry only the kind of host, never the host itself.
// `data_mode` is null until the persisted demo flag loads, because before that `enabled` is only the build default.
function superProperties(): Record<string, string | number | null> {
    const { host, status, projectId } = useAuthStore.getState()
    const demo = useDemoMode.getState().enabled
    return {
        app_variant: appVariant,
        update_channel: updateChannel,
        api_host_kind: host ? hostKind(host) : null,
        data_mode: useDemoMode.persist.hasHydrated() ? (demo ? 'demo' : 'live') : null,
        project_id: status === 'signed_in' ? projectId : null,
    }
}

// Expo inlines `EXPO_PUBLIC_*` variables at build time, so they must be read as literal `process.env` members.
export function initAnalytics(): void {
    const apiKey = process.env.EXPO_PUBLIC_POSTHOG_KEY
    if (!apiKey) {
        return
    }
    const posthog = new PostHog(apiKey, {
        host: process.env.EXPO_PUBLIC_POSTHOG_HOST || DEFAULT_HOST,
        captureAppLifecycleEvents: true,
    })
    const registerSuperProperties = (): void => {
        void posthog.register(superProperties())
    }
    registerSuperProperties()
    useAuthStore.subscribe((state, previous) => {
        if (
            state.host !== previous.host ||
            state.status !== previous.status ||
            state.projectId !== previous.projectId
        ) {
            registerSuperProperties()
        }
    })
    useDemoMode.subscribe((state, previous) => {
        if (state.enabled !== previous.enabled) {
            registerSuperProperties()
        }
    })
    useDemoMode.persist.onFinishHydration(registerSuperProperties)
    setAnalyticsClient({
        capture: (event, properties) => posthog.capture(event, definedProperties(properties)),
        screen: (name, properties) => void posthog.screen(name, definedProperties(properties)),
        captureError: (error) => posthog.captureException(error),
        identify: (distinctId) => posthog.identify(distinctId),
        reset: () => {
            posthog.reset()
            // reset() drops registered super properties with the identity.
            registerSuperProperties()
        },
    })
}
