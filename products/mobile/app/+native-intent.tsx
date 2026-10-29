import { trackWhenReady } from '@/lib/analytics'
import { deepLinkKind, webLinkTarget } from '@/lib/deepLinkKind'

// Internal builds register posthog-dev:// or posthog-preview://, see src/lib/appVariants.json.
const AUTH_CALLBACK = /^(?:posthog(?:-dev|-preview)?:\/\/|\/)callback(?:[/?#]|$)/

// On Android the OAuth redirect reaches the app as a deep link while the browser session also receives it. Without
// this filter Expo Router would open an unmatched `/callback` screen on top of sign in. iOS never gets here.
export function redirectSystemPath({ path, initial }: { path: string; initial: boolean }): string | null {
    const kind = deepLinkKind(path)
    if (kind) {
        // On a cold start Expo Router can resolve the initial URL before the root layout module runs `initAnalytics()`.
        trackWhenReady('mobile_deep_link_opened', { path_kind: kind, initial })
    }
    if (!AUTH_CALLBACK.test(path)) {
        return webLinkTarget(path) ?? path
    }
    // A cold start from a callback has no sign-in waiting for it, so start the app normally.
    return initial ? '/' : null
}
