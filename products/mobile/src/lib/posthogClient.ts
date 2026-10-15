import PostHog from 'posthog-react-native'

import { useAuthStore } from '@/auth/authStore'

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
function environmentProperties(host: string | null): Record<string, string | null> {
    return {
        app_variant: appVariant,
        update_channel: updateChannel,
        api_host_kind: host ? hostKind(host) : null,
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
    const registerEnvironment = (): void => {
        void posthog.register(environmentProperties(useAuthStore.getState().host))
    }
    registerEnvironment()
    useAuthStore.subscribe((state, previous) => {
        if (state.host !== previous.host) {
            registerEnvironment()
        }
    })
    setAnalyticsClient({
        capture: (event, properties) => posthog.capture(event, definedProperties(properties)),
        identify: (distinctId) => posthog.identify(distinctId),
        reset: () => {
            posthog.reset()
            // reset() drops registered super properties with the identity.
            registerEnvironment()
        },
    })
}
