import PostHog from 'posthog-react-native'
import { AppState, Platform } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'

import {
    type AnalyticsProperties,
    analyticsContextProperties,
    setAnalyticsClient,
    setAnalyticsContextProvider,
} from './analytics'
import { deepLinkKind } from './deepLinkKind'
import { appVariant, hostKind, updateChannel, updateId } from './environment'
import { setFeatureFlags } from './featureFlags'

const DEFAULT_HOST = 'https://us.i.posthog.com'

function definedProperties(
    properties: AnalyticsProperties | undefined
): Record<string, Exclude<AnalyticsProperties[string], undefined>> {
    const result: Record<string, Exclude<AnalyticsProperties[string], undefined>> = {}
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
function superProperties(): AnalyticsProperties {
    const { host, status, projectId, projects } = useAuthStore.getState()
    const demo = useDemoMode.getState().enabled
    const project = status === 'signed_in' && !demo ? projects.find((item) => item.id === projectId) : undefined
    return {
        client_surface: 'mobile',
        client_os: Platform.OS,
        app_variant: appVariant,
        update_channel: updateChannel,
        update_id: updateId,
        api_host_kind: host ? hostKind(host) : null,
        data_mode: useDemoMode.persist.hasHydrated() ? (demo ? 'demo' : 'live') : null,
        project_id: project?.id ?? null,
        organization_id: project?.organizationId ?? null,
        $groups: project
            ? { organization: project.organizationId, ...(project.uuid ? { project: project.uuid } : {}) }
            : {},
    }
}

// Expo inlines `EXPO_PUBLIC_*` variables at build time, so they must be read as literal `process.env` members.
export function initAnalytics(): void {
    setAnalyticsContextProvider(() => ({
        identity:
            useAuthStore.getState().status === 'signed_in'
                ? `${useAuthStore.getState().host}|${useAuthStore.getState().user?.uuid}|${sessionGeneration()}`
                : null,
        properties: superProperties(),
    }))
    const apiKey = process.env.EXPO_PUBLIC_POSTHOG_KEY
    if (!apiKey) {
        return
    }
    const posthog = new PostHog(apiKey, {
        host: process.env.EXPO_PUBLIC_POSTHOG_HOST || DEFAULT_HOST,
        captureAppLifecycleEvents: true,
        before_send: (event) => {
            if (!event) {
                return event
            }
            let properties = event.properties ?? {}
            if (event.event === 'Application Opened') {
                const { url: initialUrl, ...rest } = properties
                properties = {
                    ...rest,
                    deep_link_kind: typeof initialUrl === 'string' ? deepLinkKind(initialUrl) : null,
                }
            }
            const context = definedProperties(analyticsContextProperties())
            event.properties =
                event.event.startsWith('mobile_') || event.event === '$screen'
                    ? { ...context, ...properties, client_surface: 'mobile' }
                    : { ...properties, ...context, client_surface: 'mobile' }
            return event
        },
    })
    const registerSuperProperties = (): void => {
        void posthog.register(definedProperties(superProperties()))
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
    useAuthStore.subscribe((state, previous) => {
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
        }
    })
    useDemoMode.persist.onFinishHydration(registerSuperProperties)
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
        getSessionId: () => posthog.getSessionId(),
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
