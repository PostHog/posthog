// Internal builds register posthog-dev:// or posthog-preview://, see src/lib/appVariants.json.
const AUTH_CALLBACK = /^(?:posthog(?:-dev|-preview)?:\/\/|\/)callback(?:[/?#]|$)/

// On Android the OAuth redirect reaches the app as a deep link while the browser session also receives it. Without
// this filter Expo Router would open an unmatched `/callback` screen on top of sign in. iOS never gets here.
export function redirectSystemPath({ path, initial }: { path: string; initial: boolean }): string | null {
    if (!AUTH_CALLBACK.test(path)) {
        return path
    }
    // A cold start from a callback has no sign-in waiting for it, so start the app normally.
    return initial ? '/' : null
}
